from dataclasses import dataclass


@dataclass
class ReleaseSummary:
    """
    Lightweight release metadata included in a Marketplace listing.
    These fields can be used for an initial recommendation score
    without requesting the complete release from Discogs.
    """

    artist: str | None = None
    title: str | None = None
    year: int | None = None
    label: str | None = None
    catalog_number: str | None = None
    format: str | None = None