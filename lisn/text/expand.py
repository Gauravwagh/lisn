"""Expand text for speech: numbers, currency, dates, abbreviations, URLs.

Expansion works token by token (whitespace-separated) so that every display word maps
to a contiguous span of speech words. That mapping is what lets the player highlight the
display word while the engine reports timings for the spoken words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from num2words import num2words

_ABBREVIATIONS = {
    "e.g.": "for example",
    "i.e.": "that is",
    "etc.": "et cetera",
    "etc": "et cetera",
    "vs.": "versus",
    "vs": "versus",
    "dr.": "Doctor",
    "mr.": "Mister",
    "mrs.": "Missus",
    "ms.": "Miz",
    "prof.": "Professor",
    "sr.": "Senior",
    "jr.": "Junior",
    "approx.": "approximately",
    "dept.": "department",
    "fig.": "figure",
    "no.": "number",
    "vol.": "volume",
    "cf.": "compare",
    "viz.": "namely",
    "&": "and",
    "w/": "with",
    "w/o": "without",
    "rs.": "rupees",
    "rs": "rupees",
    "inr": "rupees",
    "usd": "dollars",
    "eur": "euros",
    "gbp": "pounds",
    "tl;dr": "too long, didn't read",
    "faq": "F A Q",
    "api": "A P I",
    "ui": "U I",
    "ux": "U X",
    "sql": "sequel",
    "cli": "C L I",
    "url": "U R L",
    "html": "H T M L",
    "css": "C S S",
    "json": "jason",
    "yaml": "yammel",
    "ok": "okay",
}

_CURRENCY = {
    "₹": ("rupee", "rupees", "paisa", "paise"),
    "$": ("dollar", "dollars", "cent", "cents"),
    "€": ("euro", "euros", "cent", "cents"),
    "£": ("pound", "pounds", "penny", "pence"),
    "¥": ("yen", "yen", "sen", "sen"),
}

_UNITS = {
    "km": "kilometers",
    "m": "meters",
    "cm": "centimeters",
    "mm": "millimeters",
    "kg": "kilograms",
    "g": "grams",
    "mg": "milligrams",
    "lb": "pounds",
    "lbs": "pounds",
    "ms": "milliseconds",
    "s": "seconds",
    "sec": "seconds",
    "min": "minutes",
    "h": "hours",
    "hr": "hours",
    "hrs": "hours",
    "kb": "kilobytes",
    "mb": "megabytes",
    "gb": "gigabytes",
    "tb": "terabytes",
    "ghz": "gigahertz",
    "mhz": "megahertz",
    "mph": "miles per hour",
    "kmph": "kilometers per hour",
    "fps": "frames per second",
    "px": "pixels",
    "x": "times",
}

_MONTHS = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]  # fmt: skip

_URL_RE = re.compile(r"^(?:https?://|www\.)\S+$", re.IGNORECASE)
_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
_PATH_RE = re.compile(r"^(?:~|\.{1,2})?/[\w./-]+$")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_CURRENCY_RE = re.compile(r"^([₹$€£¥])\s?(\d[\d,]*)(?:\.(\d{1,2}))?([kmb])?$", re.IGNORECASE)
_PERCENT_RE = re.compile(r"^(-?\d[\d,]*(?:\.\d+)?)%$")
_ORDINAL_RE = re.compile(r"^(\d+)(st|nd|rd|th)$", re.IGNORECASE)
_RANGE_RE = re.compile(r"^(\d[\d,]*)[-–](\d[\d,]*)$")
_UNIT_RE = re.compile(r"^(-?\d[\d,]*(?:\.\d+)?)\s?([a-zA-Z]{1,4})$")
_NUMBER_RE = re.compile(r"^(-?)(\d[\d,]*)(?:\.(\d+))?$")
_YEAR_RE = re.compile(r"^(1[0-9]{3}|20[0-9]{2})$")
_LEADING_PUNCT_RE = re.compile(r"^[\(\[\{\"'“‘*_~`<|#]+")
_TRAILING_PUNCT_RE = re.compile(r"[\)\]\}\"'”’*_~`>|,;:!?.…]+$")
_MULTIPLIERS = {"k": "thousand", "m": "million", "b": "billion"}


@dataclass(frozen=True)
class Expansion:
    """Speech text plus, for each display word, the span of speech words it became."""

    speech_text: str
    word_map: tuple[tuple[int, int], ...]


def expand_text(text: str) -> Expansion:
    """Expand `text` for speech while recording display-word -> speech-word spans."""
    if not isinstance(text, str):
        raise TypeError(f"expand_text expects str, got {type(text).__name__}")
    speech_words: list[str] = []
    spans: list[tuple[int, int]] = []
    for token in text.split():
        expanded = expand_token(token).split()
        start = len(speech_words)
        speech_words.extend(expanded)
        spans.append((start, len(speech_words)))
    return Expansion(speech_text=" ".join(speech_words), word_map=tuple(spans))


def expand_token(token: str) -> str:
    """Expand a single whitespace-delimited token. Returns the token unchanged if no rule applies."""
    lowered = token.lower()
    stripped_abbrev = lowered.rstrip(",;:!?)\"'")
    if stripped_abbrev in _ABBREVIATIONS:
        return _ABBREVIATIONS[stripped_abbrev] + token[len(stripped_abbrev) :]
    prefix_match = _LEADING_PUNCT_RE.match(token)
    prefix = prefix_match.group(0) if prefix_match else ""
    body = token[len(prefix) :]
    suffix_match = _TRAILING_PUNCT_RE.search(body)
    suffix = suffix_match.group(0) if suffix_match else ""
    core = body[: len(body) - len(suffix)] if suffix else body
    if not core or not any(ch.isalnum() for ch in core):
        return _punct_only(core or token)
    if _URL_RE.match(core):
        return "link"
    if _EMAIL_RE.match(core):
        return "email address"
    expanded = _expand_core(core)
    if expanded == core:
        return token
    return f"{prefix}{expanded}{suffix}"


_DASH_ONLY_RE = re.compile(r"^[-–—]+$")


def _punct_only(token: str) -> str:
    """A token with no letters or digits: dashes become a pause, other symbols are dropped."""
    if _DASH_ONLY_RE.match(token):
        return ","
    return token if any(ch in token for ch in ".,;:!?") and len(token) <= 3 else ""


def _expand_core(core: str) -> str:
    for rule in (
        _expand_iso_date,
        _expand_time,
        _expand_currency,
        _expand_percent,
        _expand_ordinal,
        _expand_range,
        _expand_unit,
        _expand_path,
        _expand_number,
    ):
        result = rule(core)
        if result is not None:
            return result
    return core


def _expand_iso_date(core: str) -> str | None:
    match = _ISO_DATE_RE.match(core)
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    return f"{_MONTHS[parsed.month - 1]} {_ordinal(parsed.day)}, {_year(parsed.year)}"


def _expand_time(core: str) -> str | None:
    match = _TIME_RE.match(core)
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        return None
    spoken_hour = _cardinal(hours)
    if minutes == 0:
        return f"{spoken_hour} o'clock"
    if minutes < 10:
        return f"{spoken_hour} oh {_cardinal(minutes)}"
    return f"{spoken_hour} {_cardinal(minutes)}"


def _expand_currency(core: str) -> str | None:
    match = _CURRENCY_RE.match(core)
    if not match:
        return None
    symbol, whole_raw, cents_raw, multiplier = match.groups()
    singular, plural, cent_singular, cent_plural = _CURRENCY[symbol]
    whole = int(whole_raw.replace(",", ""))
    if multiplier:
        return f"{_cardinal(whole)} {_MULTIPLIERS[multiplier.lower()]} {plural}"
    unit = singular if whole == 1 else plural
    spoken = f"{_cardinal(whole)} {unit}"
    if cents_raw:
        cents = int(cents_raw.ljust(2, "0"))
        if cents:
            cent_unit = cent_singular if cents == 1 else cent_plural
            spoken = f"{spoken} and {_cardinal(cents)} {cent_unit}"
    return spoken


def _expand_percent(core: str) -> str | None:
    match = _PERCENT_RE.match(core)
    if not match:
        return None
    return f"{_expand_number(match.group(1))} percent"


def _expand_ordinal(core: str) -> str | None:
    match = _ORDINAL_RE.match(core)
    if not match:
        return None
    return _ordinal(int(match.group(1)))


def _expand_range(core: str) -> str | None:
    match = _RANGE_RE.match(core)
    if not match:
        return None
    return f"{_expand_number(match.group(1))} to {_expand_number(match.group(2))}"


def _expand_unit(core: str) -> str | None:
    match = _UNIT_RE.match(core)
    if not match:
        return None
    number, unit = match.group(1), match.group(2)
    name = _UNITS.get(unit.lower()) if unit.isupper() or unit.islower() else None
    if name is None:
        return None
    return f"{_expand_number(number)} {name}"


def _expand_path(core: str) -> str | None:
    if _PATH_RE.match(core) and core.count("/") >= 2:
        return "file path"
    return None


def _expand_number(core: str) -> str | None:
    match = _NUMBER_RE.match(core)
    if not match:
        return None
    sign, whole_raw, fraction = match.groups()
    if fraction is None and _YEAR_RE.match(whole_raw):
        spoken = _year(int(whole_raw))
    else:
        whole = int(whole_raw.replace(",", ""))
        spoken = _cardinal(whole)
        if fraction is not None:
            digits = " ".join(_cardinal(int(d)) for d in fraction)
            spoken = f"{spoken} point {digits}"
    return f"minus {spoken}" if sign else spoken


def _cardinal(value: int) -> str:
    return num2words(value, lang="en").replace("-", " ")


def _ordinal(value: int) -> str:
    return num2words(value, lang="en", to="ordinal").replace("-", " ")


def _year(value: int) -> str:
    if 2000 <= value <= 2009:
        return _cardinal(value)
    return num2words(value, lang="en", to="year").replace("-", " ")
