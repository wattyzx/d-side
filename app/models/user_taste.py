from dataclasses import dataclass, field


@dataclass
class TasteProfile:
    """
    Summary of a user's musical taste inferred from their collection.

    Values currently represent occurrence counts.
    """

    artists: dict[str, int] = field(default_factory=dict)
    genres: dict[str, int] = field(default_factory=dict)
    styles: dict[str, int] = field(default_factory=dict)
    labels: dict[str, int] = field(default_factory=dict)
    years: dict[int, int] = field(default_factory=dict)