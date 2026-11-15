import random

from faker import Faker

from vault_synth import data
from vault_synth.checks import TEST_CARD_NUMBERS
from vault_synth.household import CastMember
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import DrawOpts, Page

PAGE = (428.0, 270.0)
N_PEOPLE = (1, 1)
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


def draw(
    s: Sheet, rng: random.Random, fake: Faker, cast: list[CastMember], opts: DrawOpts
) -> Truth:
    holder = cast[0].printed.upper()
    t = Truth(person=cast[0].printed)
    pg = Page(s, t, rng, opts)
    color = rng.choice(["#1f3b66", "#4a2a63", "#14554a", "#7a2e2e"])
    s.rect(0, 0, 428, 270, fill=color, stroke=None)
    bank = rng.choice(data.BANKS)
    pg.line("bank", bank, bank, 24, 22, 15, font="Helvetica-Bold", color="#ffffff")
    s.put("Credit Card", 404, 26, 10, color="#d8d8e8", align="r")
    s.rect(24, 70, 46, 34, fill="#d9b44a", stroke=None)

    number = rng.choice(_NUMBERS)
    grouped = _grouped(number)
    pg.line("number", number, grouped, 24, 124, 20, font="Courier-Bold", color="#ffffff")
    exp = data.REFERENCE_DATE.replace(year=data.REFERENCE_DATE.year + rng.randint(2, 5))
    expiry = f"{rng.randint(1, 12):02d}/{exp.year % 100:02d}"
    s.put("VALID THRU", 24, 164, 7, color="#d8d8e8")
    pg.line("expiry", expiry, expiry, 90, 160, 12, font="Courier-Bold", color="#ffffff")
    pg.line(
        "holder",
        holder,
        holder,
        24,
        196,
        13,
        font="Courier-Bold",
        color="#ffffff",
        people=[cast[0].person_id],
    )
    network = _network(number)
    pg.line(
        "network",
        network,
        network,
        404,
        224,
        14,
        font="Helvetica-BoldOblique",
        color="#ffffff",
        align="r",
        optional=True,
    )
    s.put("SPECIMEN", 24, 232, 16, font="Helvetica-Bold", color="#ffd84a")
    return t


def draw_back(s: Sheet, rng: random.Random) -> tuple[str, int]:
    """The back of the card: a signature strip with the 3-digit CVV, a care line and SPECIMEN.

    Returns the CVV and the index of the line that prints it. The value is random and means
    nothing; it is not tied to any card.
    """
    color = "#2b2b2b"
    s.rect(0, 0, 428, 270, fill="#e9e9ef", stroke=None)
    s.rect(0, 28, 428, 40, fill=color, stroke=None)
    s.rect(24, 92, 270, 34, fill="#ffffff", stroke="#999999")
    s.put("Authorised signature", 24, 130, 7, color="#555555")
    cvv = f"{rng.randint(0, 999):03d}"
    s.rect(306, 92, 60, 34, fill="#ffffff", stroke="#999999")
    idx = s.put(cvv, 336, 100, 14, font="Courier-Bold", align="c")
    s.put("CVV", 336, 130, 7, color="#555555", align="c")
    s.put(f"Customer care: {data.helpline(rng)}", 24, 176, 9, color="#333333")
    s.put("This card remains the property of the issuing bank.", 24, 192, 8, color="#555555")
    s.put("SPECIMEN", 24, 226, 16, font="Helvetica-Bold", color="#aa2222")
    return cvv, idx
