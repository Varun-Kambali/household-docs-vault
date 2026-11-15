import random

from faker import Faker

from vault_synth import data
from vault_synth.household import CastMember
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import GREY, DrawOpts, Page, band

PAGE = (595.0, 842.0)
N_PEOPLE = (1, 1)
INSURERS = [
    ("ICICI Lombard General Insurance Company Limited", "#a8491f"),
    ("Bajaj Allianz General Insurance Company Limited", "#1f4f8f"),
    ("Tata AIG General Insurance Company Limited", "#2a5f8a"),
]
VEHICLES = [
    ("Maruti Suzuki", "Swift VXI"),
    ("Hyundai", "i20 Sportz"),
    ("Honda", "Activa 6G"),
    ("Tata", "Nexon XZ"),
]


def draw(
    s: Sheet, rng: random.Random, fake: Faker, cast: list[CastMember], opts: DrawOpts
) -> Truth:
    insurer, color = rng.choice(INSURERS)
    holder = cast[0].printed
    t = Truth(person=holder)
    pg = Page(s, t, rng, opts)
    start = data.past_date(rng, 30, 330)
    end = data.plus_year(start)

    band(s, 0, 78, color)
    i = s.put(insurer, 40, 22, 16, font="Helvetica-Bold", color="#ffffff")
    t.add("insurer", insurer, insurer, [i])
    s.put(
        "Private Car Package Policy - Certificate cum Policy Schedule", 40, 50, 11, color="#f6e9e1"
    )

    pol = f"3001/{data.digits(rng, 8)}/00/000"
    y = 100
    s.put("Policy details", 40, y, 12, font="Helvetica-Bold")
    s.hline(40, 555, y + 18)
    pg.row("policy_number", "Policy Number", pol, pol, top=y + 28)
    pg.row("policyholder", "Insured Name", holder, holder, top=y + 50, people=[cast[0].person_id])
    sd, ed = data.dmy(start), data.dmy(end)
    pg.row("start_date", "Period of Insurance From", sd, data.iso(start), top=y + 72)
    pg.row("end_date", "Period of Insurance To", ed, data.iso(end), top=y + 94)
    s.put("(midnight to midnight)", 290, y + 96, 8, color=GREY)

    y = 240
    make, model = rng.choice(VEHICLES)
    s.put("Vehicle details", 40, y, 12, font="Helvetica-Bold")
    s.hline(40, 555, y + 18)
    reg = f"KA{rng.randint(1, 60):02d}{data.letters(rng, 2)}{rng.randint(1000, 9999)}"
    pg.row("registration_number", "Registration No.", reg, reg, top=y + 28)
    s.put("Make / Model", 40, y + 50, 9, color=GREY)
    s.put(f"{make} / {model}", 190, y + 50, 10, font="Helvetica-Bold")
    s.put("Chassis No. (last 5)", 40, y + 72, 9, color=GREY)
    s.put(f"XXXXXXXXXXXX{data.digits(rng, 5)}", 190, y + 72, 10, font="Helvetica-Bold")
    s.put("Year of manufacture", 40, y + 94, 9, color=GREY)
    s.put(str(rng.randint(2016, 2025)), 190, y + 94, 10, font="Helvetica-Bold")

    y = 380
    s.put("Premium and cover", 40, y, 12, font="Helvetica-Bold")
    s.hline(40, 555, y + 18)
    idv = rng.choice([385000, 512000, 640000, 785000, 42000])
    idvp = f"Rs. {data.indian_grouping(idv)}"
    pg.row(
        "idv",
        "Insured Declared Value (IDV)",
        idvp,
        str(idv),
        top=y + 28,
        value_x=230,
        optional=True,
    )
    ncb = rng.choice([20, 25, 35, 45, 50])
    pg.row(
        "ncb_percent", "No Claim Bonus", f"{ncb}%", str(ncb), top=y + 50, value_x=230, optional=True
    )
    own = rng.choice([4120, 6350, 8890, 11240])
    s.put("Own damage premium", 40, y + 84, 10)
    s.put(f"Rs. {data.indian_grouping(own)}", 555, y + 84, 10, align="r")
    s.put("Third party premium", 40, y + 104, 10)
    s.put("Rs. 3,416", 555, y + 104, 10, align="r")
    gst = round((own + 3416) * 0.18)
    s.put("GST at 18%", 40, y + 124, 10)
    s.put(f"Rs. {data.indian_grouping(gst)}", 555, y + 124, 10, align="r")
    s.hline(40, 555, y + 144, "#555555")
    total = own + 3416 + gst
    s.put("Total premium", 40, y + 152, 10, font="Helvetica-Bold")
    tp = f"Rs. {data.indian_grouping(total)}"
    i = s.put(tp, 555, y + 152, 11, font="Helvetica-Bold", align="r")
    t.add("premium", str(total), tp, [i])

    y = 600
    s.put(
        "After an accident, inform us within 24 hours. Do not move an unsafe vehicle.",
        40,
        y,
        9,
        color=GREY,
    )
    hl = data.helpline(rng)
    if not pg.gone("claim_helpline", optional=True):
        s.put("24x7 claims helpline", 40, y + 34, 9, color=GREY)
        i = s.put(hl, 150, y + 32, 11, font="Helvetica-Bold")
        t.add("claim_helpline", hl, hl, [i])
    s.put(
        "This is a computer generated schedule. Specimen data for software testing only.",
        40,
        800,
        8,
        color=GREY,
    )
    return t
