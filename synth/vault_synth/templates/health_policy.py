import random

from faker import Faker

from vault_synth import data
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import GREY, band, row

PAGE = (595.0, 842.0)
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


def draw(s: Sheet, rng: random.Random, fake: Faker) -> Truth:
    insurer, color = rng.choice(INSURERS)
    holder = fake.name()
    t = Truth(person=holder)
    start = data.past_date(rng, 30, 330)
    end = data.plus_year(start)
    members = [holder]
    for _ in range(rng.randint(1, 3)):
        members.append(fake.name().split()[0] + " " + holder.split()[-1])

    band(s, 0, 78, color)
    i = s.put(insurer, 40, 22, 17, font="Helvetica-Bold", color="#ffffff")
    t.add("insurer", insurer, insurer, [i])
    s.put("Health Insurance - Policy Schedule", 40, 50, 11, color="#f0e6e6")
    s.put("Policy period and details", 40, 98, 12, font="Helvetica-Bold")
    s.hline(40, 555, 116)

    pol = f"P/{rng.randint(10, 99)}/{rng.randint(1000, 9999)}/{data.digits(rng, 7)}"
    y = 128
    row(s, t, "policy_number", "Policy Number", pol, pol, x=40, top=y, value_x=190)
    row(s, t, "policyholder", "Policyholder", holder, holder, x=40, top=y + 22, value_x=190)
    sd, ed = data.dmy(start), data.dmy(end)
    row(s, t, "start_date", "Start Date", sd, data.iso(start), x=40, top=y + 44, value_x=190)
    row(s, t, "end_date", "End Date", ed, data.iso(end), x=40, top=y + 66, value_x=190)
    s.put("Product", 330, y, 9, color=GREY)
    s.put(
        rng.choice(["Family Health Optima", "Comprehensive Health Plan", "Health Shield"]),
        330,
        y + 14,
        10,
        font="Helvetica-Bold",
    )
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
    t.add("insured", "; ".join(members), "\n".join(members), idxs)

    y = y + 44 + len(members) * 22 + 14
    nominee = fake.name()
    row(s, t, "nominee", "Nominee", nominee, nominee, x=40, top=y, value_x=190)
    si = rng.choice([300000, 500000, 1000000, 1500000])
    sip = f"Rs. {data.indian_grouping(si)}"
    row(s, t, "sum_insured", "Sum Insured", sip, str(si), x=40, top=y + 22, value_x=190)

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
