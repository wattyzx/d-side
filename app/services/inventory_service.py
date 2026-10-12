import httpx

from app.models.inventory_item import InventoryItem
from app.models.listing import Listing
from app.services.discogs_client import get_release
from app.services.search_control import check_cancelled
from app.config import get_settings
from app.services.release_cache import ReleaseCache


_settings = get_settings()
_release_cache = ReleaseCache(_settings.release_cache_max_entries, _settings.release_cache_ttl_seconds)

def link_listing(listing: Listing, *, delay: float = 1.1) -> InventoryItem | None:
    """
    Retrieve the full release metadata associated with a Marketplace listing.

    A Discogs inventory listing contains only limited release information.
    This function uses the release ID to retrieve the complete Release object
    and combines both objects into an InventoryItem.
    Return None if this release lookup reports a missing or removed release.
    """

    check_cancelled()
    release_id = listing.release_id

    release = _release_cache.get(release_id)
    if release is None:
        try:
            release = get_release(release_id, min_interval=delay)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (404, 410):
                return None
            raise
        _release_cache.set(release_id, release)

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

    items = []
    skipped_ids = set()
    for listing in listings:
        check_cancelled()
        if listing.release_id in skipped_ids:
            continue
        item = link_listing(listing, delay=delay)
        if item is None:
            skipped_ids.add(listing.release_id)
        else:
            items.append(item)
    return items

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

def choose_inventory_pages(
    total_pages: int,
    sample_pages: int,
) -> list[int]:
    """
    Select pages distributed across the full seller inventory.

    If the requested sample is larger than the inventory,
    return every page.
    """

    if total_pages <= 0 or sample_pages <= 0:
        return []

    if sample_pages >= total_pages:
        return list(range(1, total_pages + 1))

    if sample_pages == 1:
        return [1]

    pages = [
        round(i * (total_pages - 1) / (sample_pages - 1)) + 1
        for i in range(sample_pages)
    ]

    return sorted(set(pages))
