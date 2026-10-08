from dataclasses import dataclass, field


@dataclass
class Release:
    """
    Internal representation of a music release.
    Only the metadata that may be useful for recommendations.
    Keeping this model independent from Discogs to work not only with Discogs API
    """

    id: int
    title: str

    artists: list[str] = field(default_factory=list)

    year: int | None = None

    genres: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)

    labels: list[str] = field(default_factory=list)
    catalog_numbers: list[str] = field(default_factory=list)

    formats: list[str] = field(default_factory=list)

    thumbnail_url: str | None = None
    videos: list[dict] = field(default_factory=list)
