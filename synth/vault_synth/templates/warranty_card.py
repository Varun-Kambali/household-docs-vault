import random

from faker import Faker

from vault_synth import data
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import GREY, band, row

PAGE = (595.0, 842.0)
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


def draw(s: Sheet, rng: random.Random, fake: Faker) -> Truth:
    brand, product, model_tpl, color, parts = rng.choice(PRODUCTS)
    t = Truth(person=fake.name())
    band(s, 0, 90, color)
    i = s.put(brand, 40, 26, 30, font="Helvetica-Bold", color="#ffffff")
    t.add("brand", brand, brand, [i])
    s.put("Warranty Card", 555, 40, 16, color="#ffffff", align="r")

    y = 120
    s.put("Product details", 40, y, 12, font="Helvetica-Bold")
    s.hline(40, 555, y + 18)
    row(s, t, "product", "Product", product, product, x=40, top=y + 28, value_x=190)
    model = model_tpl.format(n=rng.randint(100, 999))
    mline = s.put(model, 190, y + 50, 10, font="Helvetica-Bold")
    s.put("Model", 40, y + 50, 9, color=GREY)
    t.add("model", model, model, [mline])
    serial = f"{rng.randint(100, 999)}{data.letters(rng, 3)}{data.digits(rng, 6)}"
    sline = s.put(serial, 190, y + 72, 10, font="Helvetica-Bold")
    s.put("Serial number", 40, y + 72, 9, color=GREY)
    t.add("serial_number", serial, serial, [sline])

    y = 250
    s.put("Purchase details", 40, y, 12, font="Helvetica-Bold")
    s.hline(40, 555, y + 18)
    pd = data.past_date(rng, 60, 700)
    row(
        s,
        t,
        "purchase_date",
        "Date of purchase",
        data.dmy(pd),
        data.iso(pd),
        x=40,
        top=y + 28,
        value_x=190,
    )
    store = rng.choice(STORES)
    row(s, t, "seller", "Dealer", store, store, x=40, top=y + 50, value_x=190)
    city = rng.choice(data.CITIES)[0]
    row(s, t, "seller_location", "Dealer location", city, city, x=40, top=y + 72, value_x=190)
    s.put("Customer", 40, y + 94, 9, color=GREY)
    s.put(t.person, 190, y + 94, 10)

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
    t.add("warranty_parts", ";".join(f"{p}:{y_}" for p, y_ in parts), "\n".join(texts), idxs)

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
