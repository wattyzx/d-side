"""Shared placeholder rules for taste profiles and recommendation scores."""

import re


GENERIC_ARTISTS = frozenset({
    "", "various", "various artist", "various artists",
    "unknown", "unknown artist", "unknown artists",
})
GENERIC_LABELS = frozenset({
    "", "unknown", "unknown label", "not on label", "white label",
})


def _placeholder_key(value: str | None) -> str:
    normalized = " ".join((value or "").casefold().split())
    # Discogs can append a numeric disambiguation suffix to a name.
    return re.sub(r"\s*\(\d+\)$", "", normalized).strip()


def is_generic_artist(value: str | None) -> bool:
    return _placeholder_key(value) in GENERIC_ARTISTS


def is_generic_label(value: str | None) -> bool:
    return _placeholder_key(value) in GENERIC_LABELS
