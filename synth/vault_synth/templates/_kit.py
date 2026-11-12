"""Small drawing helpers shared by the templates."""

from vault_synth.sheet import Sheet, Truth

GREY = "#666666"


def band(s: Sheet, top: float, height: float, color: str) -> None:
    s.rect(0, top, s.w, height, fill=color, stroke=None)


def row(
    s: Sheet,
    t: Truth,
    name: str,
    label: str,
    printed: str,
    value: str,
    *,
    x: float,
    top: float,
    value_x: float,
    size: float = 10,
) -> int:
    """A label and its value on one row; the value line supports the field."""
    s.put(label, x, top, size - 1, color=GREY)
    idx = s.put(printed, value_x, top, size, font="Helvetica-Bold")
    t.add(name, value, printed, [idx])
    return idx


def person_from(name: str) -> str:
    return " ".join(name.split())
