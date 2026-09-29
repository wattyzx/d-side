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
    in_wantlist: bool = False
    in_collection: bool = False
    community_have: int = 0
    community_want: int = 0