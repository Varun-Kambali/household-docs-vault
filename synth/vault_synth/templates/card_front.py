import random

from faker import Faker

from vault_synth import data
from vault_synth.checks import TEST_CARD_NUMBERS
from vault_synth.sheet import Sheet, Truth

PAGE = (428.0, 270.0)
_NUMBERS = sorted(TEST_CARD_NUMBERS)


def _network(number: str) -> str:
    if number.startswith("4"):
        return "VISA"
    if number.startswith("5"):
        return "Mastercard"
    if number.startswith("37"):
        return "American Express"
    if number.startswith("6011"):
        return "Discover"
    return "Diners Club"


def _grouped(number: str) -> str:
    if len(number) == 15:
        return f"{number[:4]} {number[4:10]} {number[10:]}"
    return " ".join(number[i : i + 4] for i in range(0, len(number), 4))


def draw(s: Sheet, rng: random.Random, fake: Faker) -> Truth:
    holder = fake.name().upper()
    t = Truth(person=holder.title())
    color = rng.choice(["#1f3b66", "#4a2a63", "#14554a", "#7a2e2e"])
    s.rect(0, 0, 428, 270, fill=color, stroke=None)
    bank = rng.choice(data.BANKS)
    i = s.put(bank, 24, 22, 15, font="Helvetica-Bold", color="#ffffff")
    t.add("bank", bank, bank, [i])
    s.put("Credit Card", 404, 26, 10, color="#d8d8e8", align="r")
    s.rect(24, 70, 46, 34, fill="#d9b44a", stroke=None)

    number = rng.choice(_NUMBERS)
    grouped = _grouped(number)
    i = s.put(grouped, 24, 124, 20, font="Courier-Bold", color="#ffffff")
    t.add("number", grouped, grouped, [i])
    exp = data.REFERENCE_DATE.replace(year=data.REFERENCE_DATE.year + rng.randint(2, 5))
    expiry = f"{rng.randint(1, 12):02d}/{exp.year % 100:02d}"
    s.put("VALID THRU", 24, 164, 7, color="#d8d8e8")
    i = s.put(expiry, 90, 160, 12, font="Courier-Bold", color="#ffffff")
    t.add("expiry", expiry, expiry, [i])
    i = s.put(holder, 24, 196, 13, font="Courier-Bold", color="#ffffff")
    t.add("holder", holder, holder, [i])
    network = _network(number)
    i = s.put(network, 404, 224, 14, font="Helvetica-BoldOblique", color="#ffffff", align="r")
    t.add("network", network, network, [i])
    s.put("SPECIMEN", 24, 232, 16, font="Helvetica-Bold", color="#ffd84a")
    return t
