"""The shared form page: an issuer band, a title, label and value rows, one line per list item,
a short notice and a SPECIMEN footer. Which fields it prints comes from a `FormSpec`."""

import random

from faker import Faker

from household_vault.doctypes import AREA, Area, DocType
from vault_synth.forms import FORM_SPECS, ORG_PRIORITY, PERSON_FIELDS, PERSON_LIST_FIELDS, FormSpec
from vault_synth.household import CastMember
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import GREY, DrawOpts, Page, band

PAGE = (595.0, 842.0)
BANDS = ("#2d5a6a", "#5a3d6a", "#2f5d3a", "#6a4a2d", "#3a4a7a")
NOTICE = (
    "This document is computer generated and valid without a signature.",
    "Keep it safe; you may be asked for it when you claim, renew or transfer.",
)
LIST_X = 60


def draw_form(
    spec: FormSpec,
    s: Sheet,
    rng: random.Random,
    fake: Faker,
    cast: list[CastMember],
    opts: DrawOpts,
    *,
    identity: bool = False,
) -> Truth:
    t = Truth(person=cast[0].printed)
    pg = Page(s, t, rng, opts)
    band_color = rng.choice(BANDS)
    planned = spec.joint(rng) if spec.joint else {}

    y = 112.0
    for f in spec.fields:
        value, printed = planned[f.name] if f.name in planned else f.make(rng, fake, cast)
        label = spec.person_label if f.name in PERSON_FIELDS else f.label
        optional = f.name not in spec.required and not (
            f.name in PERSON_FIELDS or f.name in PERSON_LIST_FIELDS
        )
        who: list[str | None] | None = None
        if f.name in PERSON_FIELDS:
            who = [cast[0].person_id]
        elif f.name in PERSON_LIST_FIELDS:
            who = [c.person_id for c in cast]
        if "\n" in printed or isinstance(value, list):
            if pg.gone(f.name, optional=optional):
                continue
            s.put(label, 40, y, 9, color=GREY)
            y += 15
            idxs = []
            for text in printed.split("\n"):
                idxs.append(s.put(text, LIST_X, y, 10, font="Helvetica-Bold"))
                y += 16
            t.add(f.name, value, printed, idxs, who)
            y += 6
        else:
            if (
                pg.row(
                    f.name, label, printed, value, top=y, value_x=200, optional=optional, people=who
                )
                is not None
            ):
                y += 24

    # the band is drawn last, so it can name the organisation the page printed (priority order
    # in `ORG_PRIORITY`); a page without one, or that left it off, names an issuer of the type
    names = {f.name for f in spec.fields}
    org = next((n for n in ORG_PRIORITY if n in names), None)
    heading = t.printed[org] if org is not None and org in t.printed else rng.choice(spec.issuers)
    band(s, 0, 78, band_color)
    s.put(heading, 40, 20, 15, font="Helvetica-Bold", color="#ffffff")
    s.put(spec.title, 40, 48, 11, color="#f0f0f0")
    s.hline(40, 555, 96, "#888888")

    if spec.image_box:
        s.rect(40, y + 8, 515, 260, fill="#161616", stroke="#444444")
        s.rect(60, y + 28, 215, 220, fill="#2a2a2a", stroke=None)
        s.rect(320, y + 28, 215, 220, fill="#2a2a2a", stroke=None)
        y += 280
    y += 18
    for line in NOTICE:
        s.put(line, 40, y, 9, color=GREY)
        y += 14
    if identity:
        s.put("SPECIMEN", 297, 740, 28, font="Helvetica-Bold", color="#cc1111", align="c")
    s.put("Specimen data for software testing only.", 40, 800, 8, color=GREY)
    return t


class FormTemplate:
    """A page module for one type, shaped like the hand-drawn template modules."""

    PAGE = PAGE

    def __init__(self, doc_type: DocType) -> None:
        self.doc_type = doc_type
        self.spec = FORM_SPECS[doc_type]
        # marriage prints both parties; policies with an insured list print up to three people
        names = {f.name for f in self.spec.fields}
        if "parties" in names:
            self.N_PEOPLE = (2, 2)
        elif "insured" in names:
            self.N_PEOPLE = (1, 3)
        else:
            self.N_PEOPLE = (1, 1)

    def draw(
        self, s: Sheet, rng: random.Random, fake: Faker, cast: list[CastMember], opts: DrawOpts
    ) -> Truth:
        identity = AREA[self.doc_type] is Area.identity
        return draw_form(self.spec, s, rng, fake, cast, opts, identity=identity)
