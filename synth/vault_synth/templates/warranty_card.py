import random

from faker import Faker

from vault_synth import data
from vault_synth.household import CastMember
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import GREY, DrawOpts, Page, band

PAGE = (595.0, 842.0)
N_PEOPLE = (1, 1)
PRODUCTS = [
    (
        "LG",
        "Double Door Refrigerator 242 L",
        "GL-S{n}ZPZX",
        "#a50034",
        [("Compressor", 10), ("Product", 1)],
    ),
    (
        "Samsung",
        "Front Load Washing Machine 8 kg",
        "WW80{n}FN",
        "#1428a0",
        [("Digital Inverter Motor", 10), ("Product", 2)],
    ),
    (
        "Whirlpool",
        "Convection Microwave Oven 25 L",
        "MWO-{n}C",
        "#c8a000",
        [("Magnetron", 2), ("Product", 1)],
    ),
    (
        "Sony",
        "Bravia LED Television 43 inch",
        "KD-43X{n}",
        "#222222",
        [("Panel", 2), ("Product", 1)],
    ),
    (
        "Voltas",
        "Split Air Conditioner 1.5 Ton",
        "183V-{n}",
        "#0b5ea8",
        [("Compressor", 5), ("PCB", 2), ("Product", 1)],
    ),
]
STORES = [
    "Metro Home Appliances",
    "City Electronics Mart",
    "Sri Lakshmi Home Needs",
    "Vijaya Digital World",
]


def draw(
    s: Sheet, rng: random.Random, fake: Faker, cast: list[CastMember], opts: DrawOpts
) -> Truth:
    brand, product, model_tpl, color, parts = rng.choice(PRODUCTS)
    t = Truth(person=cast[0].printed)
    pg = Page(s, t, rng, opts)
    band(s, 0, 90, color)
    pg.line("brand", brand, brand, 40, 26, 30, font="Helvetica-Bold", color="#ffffff")
    s.put("Warranty Card", 555, 40, 16, color="#ffffff", align="r")

    y = 120
    s.put("Product details", 40, y, 12, font="Helvetica-Bold")
    s.hline(40, 555, y + 18)
    pg.row("product", "Product", product, product, top=y + 28)
    model = model_tpl.format(n=rng.randint(100, 999))
    pg.row("model", "Model", model, model, top=y + 50, size=10, optional=True)
    serial = f"{rng.randint(100, 999)}{data.letters(rng, 3)}{data.digits(rng, 6)}"
    pg.row("serial_number", "Serial number", serial, serial, top=y + 72, optional=True)

    y = 250
    s.put("Purchase details", 40, y, 12, font="Helvetica-Bold")
    s.hline(40, 555, y + 18)
    pd = data.past_date(rng, 60, 700)
    pg.row("purchase_date", "Date of purchase", data.dmy(pd), data.iso(pd), top=y + 28)
    store = rng.choice(STORES)
    pg.row("seller", "Dealer", store, store, top=y + 50, optional=True)
    city = rng.choice(data.CITIES)[0]
    pg.row("seller_location", "Dealer location", city, city, top=y + 72, optional=True)
    buyer = cast[0]
    pg.row(
        "buyer",
        "Customer",
        buyer.printed,
        buyer.printed,
        top=y + 94,
        people=[buyer.person_id],
        optional=True,
    )

    y = 400
    s.put("Warranty terms", 40, y, 12, font="Helvetica-Bold")
    s.hline(40, 555, y + 18)
    s.put("Part and warranty period", 40, y + 26, 9, color=GREY)
    idxs, texts = [], []
    for n, (part, years) in enumerate(parts):
        top = y + 46 + n * 22
        label = f"{part} - {years} year" + ("s" if years > 1 else "")
        idxs.append(s.put(label, 40, top, 10, font="Helvetica-Bold"))
        texts.append(label)
    t.add(
        "warranty_parts",
        [{"part": p, "years": y_} for p, y_ in parts],
        "\n".join(texts),
        idxs,
    )

    y = 560
    for n, line in enumerate(
        [
            "1. Warranty starts on the date of purchase shown on the original invoice.",
            "2. Keep this card and the invoice. Service is refused without them.",
            "3. Damage from misuse, power surges or unauthorised repair is not covered.",
            "4. Consumables and accessories carry no warranty.",
        ]
    ):
        s.put(line, 40, y + n * 16, 9, color=GREY)
    s.put("Authorised signature and seal", 555, 760, 9, color=GREY, align="r")
    s.put("Specimen data for software testing only.", 40, 800, 8, color=GREY)
    return t
