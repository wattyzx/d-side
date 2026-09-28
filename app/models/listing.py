from dataclasses import dataclass


@dataclass
class Listing:
    """
    Representation of a Discogs Marketplace listing.

    A Listing represents an item for sale, while Release represents
    the musical release itself.
    """

    id: int
    release_id: int

    price: float
    currency: str

    condition: str
    sleeve_condition: str | None = None