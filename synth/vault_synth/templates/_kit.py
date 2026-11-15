"""Small drawing helpers shared by the templates."""

import random
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from vault_synth.sheet import Sheet, Truth

GREY = "#666666"


@dataclass(frozen=True)
class DrawOpts:
    """What a page leaves off: optional rows at `absent_rate`, and one required field if asked."""

    absent_rate: float
    drop_required: str | None = None


def band(s: Sheet, top: float, height: float, color: str) -> None:
    s.rect(0, top, s.w, height, fill=color, stroke=None)


def left_off(
    opts: DrawOpts, rng: random.Random, name: str | None = None, *, optional: bool = False
) -> bool:
    """True when this field stays off the page: it is the dropped required one, or an optional
    one that lost its roll. Every optional field takes its roll, so later draws stay in step."""
    gone = optional and rng.random() < opts.absent_rate
    return gone or (name is not None and name == opts.drop_required)


def row(
    s: Sheet,
    t: Truth,
    name: str,
    label: str,
    printed: str,
    value: JsonValue,
    *,
    x: float,
    top: float,
    value_x: float,
    size: float = 10,
    opts: DrawOpts,
    rng: random.Random,
    optional: bool = False,
    people: list[str | None] | None = None,
) -> int | None:
    """A label and its value on one row; the value line supports the field.

    An optional row, or the required row `opts` drops, leaves the page without its label too.
    """
    if left_off(opts, rng, name, optional=optional):
        return None
    s.put(label, x, top, size - 1, color=GREY)
    idx = s.put(printed, value_x, top, size, font="Helvetica-Bold")
    t.add(name, value, printed, [idx], people)
    return idx


class Page:
    """A sheet, its truth and the page's absent-field settings, so a template reads as a layout."""

    def __init__(self, s: Sheet, t: Truth, rng: random.Random, opts: DrawOpts) -> None:
        self.s, self.t, self.rng, self.opts = s, t, rng, opts

    def gone(self, name: str, *, optional: bool = False) -> bool:
        """Roll for a field the template draws itself; True when it stays off the page."""
        return left_off(self.opts, self.rng, name, optional=optional)

    def row(
        self,
        name: str,
        label: str,
        printed: str,
        value: JsonValue,
        *,
        top: float,
        x: float = 40,
        value_x: float = 190,
        size: float = 10,
        optional: bool = False,
        people: list[str | None] | None = None,
    ) -> int | None:
        return row(
            self.s,
            self.t,
            name,
            label,
            printed,
            value,
            x=x,
            top=top,
            value_x=value_x,
            size=size,
            opts=self.opts,
            rng=self.rng,
            optional=optional,
            people=people,
        )

    def line(
        self,
        name: str,
        value: JsonValue,
        printed: str,
        x: float,
        top: float,
        size: float = 10,
        *,
        text: str | None = None,
        optional: bool = False,
        people: list[str | None] | None = None,
        font: str = "Helvetica",
        color: str = "#111111",
        align: Literal["l", "r", "c"] = "l",
    ) -> int | None:
        """One printed line that is a field. `text` is what is drawn when a label or a prefix
        comes with the value; the field's `printed` is the value alone."""
        if self.gone(name, optional=optional):
            return None
        idx = self.s.put(text or printed, x, top, size, font=font, color=color, align=align)
        self.t.add(name, value, printed, [idx], people)
        return idx
