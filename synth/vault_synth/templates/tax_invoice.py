import random

from faker import Faker
from reportlab.pdfbase import pdfmetrics

from vault_synth import data
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import GREY, row

PAGE = (595.0, 842.0)
SELLERS = ["Croma", "Reliance Digital", "Vijay Sales", "Poorvika Mobiles", "Sangeetha Mobiles"]
ITEMS = [
    ("LG Double Door Refrigerator 242 L", "GL-S{n}ZPZX", 31990),
    ("Samsung Front Load Washing Machine 8 kg", "WW80{n}FN", 36490),
    ("Sony Bravia LED Television 43 inch", "KD-43X{n}", 38990),
    ("Voltas Split Air Conditioner 1.5 Ton", "183V-{n}", 34990),
]


def _gstin(rng: random.Random) -> str:
    pan_part = f"{data.letters(rng, 5)}{data.digits(rng, 4)}{data.letters(rng, 1)}"
    return f"29{pan_part}1Z{rng.choice('ABCDEFG0123456789')}"


def draw(s: Sheet, rng: random.Random, fake: Faker) -> Truth:
    buyer = fake.name()
    t = Truth(person=buyer)
    seller = rng.choice(SELLERS)
    city_name, state, pin = rng.choice(data.CITIES)

    s.put("TAX INVOICE", 297.5, 30, 18, font="Helvetica-Bold", align="c")
    i = s.put(seller, 40, 70, 15, font="Helvetica-Bold")
    t.add("seller", seller, seller, [i])
    s.put(f"{rng.randint(1, 90)}, {rng.choice(data.LOCALITIES)}", 40, 92, 10)
    i = s.put(city_name, 40, 106, 10)
    t.add("seller_location", city_name, city_name, [i])
    s.put(
        f", {state} - {pin}{rng.randint(0, 999):03d}",
        40 + pdfmetrics.stringWidth(city_name, "Helvetica", 10),
        106,
        10,
    )
    g = _gstin(rng)
    i = s.put(f"GSTIN: {g}", 40, 124, 10, font="Helvetica-Bold")
    t.add("gstin", g, g, [i])
    s.hline(40, 555, 148, "#555555", 0.8)

    prefix = rng.choice(["BLR", "INV", "TX"])
    inv = f"{prefix}/{rng.randint(24, 26)}-{rng.randint(25, 27)}/{data.digits(rng, 6)}"
    row(s, t, "invoice_number", "Invoice No.", inv, inv, x=40, top=160, value_x=130)
    d = data.past_date(rng, 60, 700)
    row(s, t, "invoice_date", "Invoice Date", data.dmy(d), data.iso(d), x=330, top=160, value_x=420)
    s.put("Billed to", 40, 190, 9, color=GREY)
    s.put(buyer, 40, 204, 10, font="Helvetica-Bold")
    s.put("Place of supply: Karnataka (29)", 330, 204, 9, color=GREY)

    product, mtpl, price = rng.choice(ITEMS)
    model = mtpl.format(n=rng.randint(100, 999))
    serial = f"{rng.randint(100, 999)}{data.letters(rng, 3)}{data.digits(rng, 6)}"
    top = 250
    s.rect(40, top, 515, 22, fill="#eeeeee", stroke=None)
    for x, h, al in (
        (46, "Description", "l"),
        (350, "Qty", "l"),
        (400, "Rate", "r"),
        (470, "GST", "r"),
        (550, "Amount", "r"),
    ):
        s.put(h, x, top + 6, 9, font="Helvetica-Bold", align=al)  # type: ignore[arg-type]
    pl = s.put(product, 46, top + 34, 10, font="Helvetica-Bold")
    t.add("product", product, product, [pl])
    ml = s.put(f"Model: {model}", 46, top + 50, 9)
    t.add("model", model, model, [ml])
    sl = s.put(f"Serial No: {serial}", 46, top + 64, 9)
    t.add("serial_number", serial, serial, [sl])
    base = round(price / 1.28)
    s.put("1", 350, top + 34, 10)
    s.put(data.indian_grouping(base), 400, top + 34, 10, align="r")
    s.put("28%", 470, top + 34, 10, align="r")
    s.put(data.indian_grouping(price), 550, top + 34, 10, align="r")
    s.hline(40, 555, top + 90)

    y = top + 104
    half = round((price - base) / 2)
    s.put("CGST 14%", 420, y, 10, align="r")
    s.put(data.indian_grouping(half), 550, y, 10, align="r")
    s.put("SGST 14%", 420, y + 18, 10, align="r")
    s.put(data.indian_grouping(price - base - half), 550, y + 18, 10, align="r")
    s.hline(330, 555, y + 40, "#555555")
    s.put("Grand total", 420, y + 50, 11, font="Helvetica-Bold", align="r")
    amt = data.indian_grouping(price)
    i = s.put(f"Rs. {amt}", 550, y + 50, 12, font="Helvetica-Bold", align="r")
    t.add("amount", str(price), f"Rs. {amt}", [i])
    s.put("Payment mode: Card", 40, y + 52, 9, color=GREY)
    s.put(
        "Goods once sold will not be taken back. Subject to Bengaluru jurisdiction.",
        40,
        700,
        8,
        color=GREY,
    )
    s.put("Authorised signatory", 555, 740, 9, color=GREY, align="r")
    s.put("Specimen data for software testing only.", 40, 800, 8, color=GREY)
    return t
