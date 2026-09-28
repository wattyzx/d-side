from app.models.inventory_item import InventoryItem
from app.models.listing import Listing
from app.services.discogs_client import get_release


def enrich_listing(listing: Listing) -> InventoryItem:
    """
    Retrieve the full release metadata associated with a Marketplace listing.

    A Discogs inventory listing contains only limited release information.
    This function uses the release ID to retrieve the complete Release object
    and combines both objects into an InventoryItem.
    """

    release = get_release(listing.release_id)

    return InventoryItem(
        listing=listing,
        release=release,
    )