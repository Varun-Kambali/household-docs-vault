"""Made-up names, places and formats. Nothing here belongs to a real person."""

import datetime as dt
import random

# City, state, PIN prefix. Streets and localities are invented.
CITIES = [
    ("Bengaluru", "Karnataka", "560"),
    ("Mysuru", "Karnataka", "570"),
    ("Hubballi", "Karnataka", "580"),
    ("Mangaluru", "Karnataka", "575"),
    ("Chennai", "Tamil Nadu", "600"),
    ("Hyderabad", "Telangana", "500"),
    ("Pune", "Maharashtra", "411"),
    ("Kochi", "Kerala", "682"),
]
LOCALITIES = [
    "Lakeview Layout",
    "Temple Road",
    "Green Park Colony",
    "Market Street",
    "Rose Garden Extension",
    "Palm Grove Nagar",
    "Station Road",
    "Hill View Enclave",
    "Canal Side Colony",
    "Orchard Layout",
]
KN_FIRST = [
    ("Suresh", "ಸುರೇಶ್"),
    ("Ramesh", "ರಮೇಶ್"),
    ("Mahesh", "ಮಹೇಶ್"),
    ("Girish", "ಗಿರೀಶ್"),
    ("Anil", "ಅನಿಲ್"),
    ("Kavita", "ಕವಿತಾ"),
    ("Sunita", "ಸುನೀತಾ"),
    ("Meena", "ಮೀನಾ"),
    ("Rekha", "ರೇಖಾ"),
    ("Savitha", "ಸವಿತಾ"),
    ("Naveen", "ನವೀನ್"),
    ("Kiran", "ಕಿರಣ್"),
    ("Vinay", "ವಿನಯ್"),
    ("Deepa", "ದೀಪಾ"),
]
KN_LAST = [
    ("Gowda", "ಗೌಡ"),
    ("Naik", "ನಾಯಕ್"),
    ("Rao", "ರಾವ್"),
    ("Hegde", "ಹೆಗಡೆ"),
    ("Patil", "ಪಾಟೀಲ್"),
    ("Kulkarni", "ಕುಲಕರ್ಣಿ"),
    ("Bhat", "ಭಟ್"),
]
HOSPITALS = [
    "Cauvery Care Hospital",
    "Lakeview Multispeciality Clinic",
    "Sunrise Family Hospital",
    "Hill Park Medical Centre",
    "Greenfield Polyclinic",
]
LABS = ["Aarogya Diagnostics", "Nirmala Path Labs", "Clear Lane Diagnostics", "Prima Scan and Labs"]
BANKS = ["Nilgiri Bank", "Tungabhadra Bank", "Deccan Trust Bank", "Malnad Co-operative Bank"]

# The date every document is generated around, so output does not depend on today.
REFERENCE_DATE = dt.date(2026, 11, 12)


def indian_grouping(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join([*parts, tail])


def dmy(d: dt.date) -> str:
    return d.strftime("%d/%m/%Y")


def iso(d: dt.date) -> str:
    return d.isoformat()


def past_date(rng: random.Random, min_days: int = 20, max_days: int = 900) -> dt.date:
    return REFERENCE_DATE - dt.timedelta(days=rng.randint(min_days, max_days))


def plus_year(d: dt.date, years: int = 1) -> dt.date:
    """Same day next year, less one day, the way policies state their end."""
    try:
        nxt = d.replace(year=d.year + years)
    except ValueError:  # 29 Feb
        nxt = d.replace(year=d.year + years, day=28)
    return nxt - dt.timedelta(days=1)


def digits(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(n))


def letters(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(n))


def helpline(rng: random.Random) -> str:
    return f"1800 {rng.randint(100, 999)} {rng.randint(1000, 9999)}"


def address_lines(rng: random.Random) -> tuple[list[str], str]:
    """Return printed address lines and the city name."""
    city, state, pin = rng.choice(CITIES)
    lines = [
        f"No. {rng.randint(1, 240)}, {rng.randint(1, 18)}th Cross",
        rng.choice(LOCALITIES),
        f"{city}, {state} - {pin}{rng.randint(0, 999):03d}",
    ]
    return lines, city
