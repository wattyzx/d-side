from app.models.inventory_item import InventoryItem
from app.models.listing import Listing
from app.models.release import Release
from app.services.discogs_client import get_release


_release_cache: dict[int, Release] = {}

def link_listing(listing: Listing, *, delay: float = 1.1) -> InventoryItem:
    """
    Retrieve the full release metadata associated with a Marketplace listing.

    A Discogs inventory listing contains only limited release information.
    This function uses the release ID to retrieve the complete Release object
    and combines both objects into an InventoryItem.
    """

    release_id = listing.release_id

    if release_id in _release_cache:
        release = _release_cache[release_id]
    else:
        release = get_release(release_id, min_interval=delay)
        _release_cache[release_id] = release

    return InventoryItem(
        listing=listing,
        release=release,
    )

def link_inventory(listings: list[Listing], delay: float = 1.1) -> list[InventoryItem]:
    """
    Convert a list of Marketplace listings into InventoryItem objects.
    The in-memory release cache prevents duplicate API requests
    for release IDs that have already been retrieved. The shared HTTP client
    handles pacing before actual requests; delay can increase its interval.
    """

    return [link_listing(listing, delay=delay) for listing in listings]

def group_listings_by_release(
    listings: list[Listing],
) -> dict[int, list[Listing]]:
    grouped = {}

    for listing in listings:
        grouped.setdefault(
            listing.release_id,
            [],
        ).append(listing)

    return grouped

def deduplicate_listings(
    listings: list[Listing],
) -> list[Listing]:

    grouped = group_listings_by_release(
        listings
    )

    return [
        copies[0]
        for copies in grouped.values()
    ]