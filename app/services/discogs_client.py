from dotenv import load_dotenv
from app.services.discogs_http import get_json
from app.services.release_mapper import (
    discogs_to_release,
    collection_to_releases,
    inventory_to_listings
)
from app.models.release import Release

# Load environment variables from the local .env file.
load_dotenv()

def get_release_raw(release_id: int, *, min_interval: float = 1.1) -> dict:
    """Retrieve release metadata with shared request pacing and retries."""
    return get_json(f"/releases/{release_id}", min_interval=min_interval)

def get_release(release_id: int, *, min_interval: float = 1.1) -> Release:
    """Retrieve a Discogs release and convert it into the internal model."""
    return discogs_to_release(get_release_raw(release_id, min_interval=min_interval))

def get_collection_raw(
    username: str,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Retrieve one page of a collection; folder 0 covers all folders."""
    return get_json(
        f"/users/{username}/collection/folders/0/releases",
        params={"page": page, "per_page": per_page},
    )

def get_collection(username: str) -> list[Release]:

    releases = []
    page = 1

    while True:
        collection_data = get_collection_raw(username, page=page)

        page_releases = collection_to_releases(collection_data)
        releases.extend(page_releases)

        pagination = collection_data["pagination"]

        if page >= pagination["pages"]:
            break

        page += 1

    return releases

def get_inventory_raw(
    username: str,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Retrieve one page of a seller's inventory."""
    return get_json(
        f"/users/{username}/inventory",
        params={"page": page, "per_page": per_page},
    )

def get_inventory(username: str) -> list:
    """
    Retrieve all listings from a Discogs seller inventory.

    Discogs paginates Marketplace inventories, so this function
    requests every page and combines all listings into one list.
    """

    listings = []
    page = 1

    while True:
        inventory_data = get_inventory_raw(username, page=page)

        page_listings = inventory_to_listings(inventory_data)
        listings.extend(page_listings)

        pagination = inventory_data["pagination"]

        if page >= pagination["pages"]:
            break

        page += 1

    return listings

def get_wantlist_raw(
    username: str,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Retrieve one page of a user's wantlist."""
    return get_json(
        f"/users/{username}/wants",
        params={"page": page, "per_page": per_page},
    )

def get_wantlist_ids(username: str) -> set[int]:
    """
    Retrieve all release IDs from a user's Discogs wantlist.
    """

    release_ids = set()
    page = 1

    while True:
        wantlist_data = get_wantlist_raw(username, page=page)

        for want in wantlist_data.get("wants", []):
            basic_information = want.get("basic_information", {})
            release_id = basic_information.get("id")

            if release_id is not None:
                release_ids.add(release_id)

        pagination = wantlist_data["pagination"]

        if page >= pagination["pages"]:
            break

        page += 1

    return release_ids

def search_releases_by_style_raw(
    style: str,
    page: int = 1,
    per_page: int = 100,
) -> dict:
    """Search releases by style for the candidate-generation experiment."""
    return get_json(
        "/database/search",
        params={
            "type": "release",
            "style": style,
            "format": "Vinyl",
            "page": page,
            "per_page": per_page,
        },
    )
