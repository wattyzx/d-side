from dataclasses import dataclass

from app.models.listing import Listing
from app.models.release import Release


@dataclass
class InventoryItem:
    """
    A Marketplace listing together with its full musical release metadata.

    The recommender will mainly evaluate the Release,
    while Listing contains marketplace information such as
    price and condition.
    """

    listing: Listing
    release: Release