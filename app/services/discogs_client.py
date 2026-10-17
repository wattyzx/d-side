from app.config import get_settings
from app.services.search_control import check_cancelled
from app.services.cache_service import SQLiteCache
from app.services.database import configured_database
from app.services.discogs_http import get_json, put_json
from app.services.discogs_session import current_credentials, personal_namespace
from urllib.parse import quote
from app.services.release_mapper import (
    discogs_to_release,
    collection_to_releases,
    inventory_to_listings
)
from app.models.release import Release

_settings = get_settings()
cache = SQLiteCache(_settings.cache_db_path,
                    database=configured_database(_settings, _settings.cache_db_path))
DEFAULT_PER_PAGE = 100

def get_release_raw(release_id: int, *, min_interval: float = 1.1) -> dict:
    """Retrieve release metadata with shared request pacing and retries."""
    return get_json(f"/releases/{release_id}", min_interval=min_interval)

def get_release(release_id: int, *, min_interval: float = 1.1) -> Release:
    """Retrieve a Discogs release and convert it into the internal model."""
    return discogs_to_release(get_release_raw(release_id, min_interval=min_interval))

def get_collection_raw(
    username: str,
    page: int = 1,
    per_page: int = 100,
):
    check_cancelled()
    cache_key = f"{username}:{page}:{per_page}"

    cached = cache.get(
        personal_namespace("collection_raw"),
        cache_key,
    )

    if cached is not None:
        return cached

    data = get_json(
        f"/users/{username}/collection/folders/0/releases",
        params={
            "page": page,
            "per_page": per_page,
        },
    )

    cache.set(
        personal_namespace("collection_raw"),
        cache_key,
        data,
        ttl_seconds=21600,
    )

    return data

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
    per_page: int = DEFAULT_PER_PAGE,
    sort: str | None = None,
    sort_order: str | None = None,
) -> dict:
    """Retrieve one page of a seller's inventory."""
    check_cancelled()

    cache_key = f"{username}:{page}:{per_page}:{sort}:{sort_order}"

    cached = cache.get(
        personal_namespace("inventory_raw"),
        cache_key,
    )

    if cached is not None:
        return cached

    params = {
        "page": page,
        "per_page": per_page,
    }

    if sort is not None:
        params["sort"] = sort

    if sort_order is not None:
        params["sort_order"] = sort_order

    data = get_json(
        f"/users/{username}/inventory",
        params=params,
    )

    cache.set(
        personal_namespace("inventory_raw"),
        cache_key,
        data,
        ttl_seconds=21600,
    )

    return data

def get_inventory(
    username: str,
    pages: list[int] | None = None,
) -> list:
    """
    Retrieve listings from a Discogs seller inventory.

    If pages is None, retrieve the complete inventory.
    If pages is provided, retrieve only the selected pages.
    """

    listings = []

    if pages is None:
        page = 1

        while True:
            inventory_data = get_inventory_raw(
                username,
                page=page,
            )

            page_listings = inventory_to_listings(inventory_data)
            listings.extend(page_listings)

            pagination = inventory_data["pagination"]

            if page >= pagination["pages"]:
                break

            page += 1

        return listings

    pages = sorted(set(pages))

    if not pages:
        return []

    if pages[0] != 1:
        raise ValueError(
            "Sampled inventory pages must include page 1"
        )

    for page in pages:
        inventory_data = get_inventory_raw(
            username,
            page=page,
        )

        page_listings = inventory_to_listings(inventory_data)
        listings.extend(page_listings)

    return listings

def get_wantlist_raw(
    username: str,
    page: int = 1,
    per_page: int = 100,
):
    check_cancelled()
    cache_key = f"{username}:{page}:{per_page}"
    namespace = personal_namespace("wantlist_raw")

    cached = cache.get(
        namespace,
        cache_key,
    )

    if cached is not None:
        return cached

    version = cache.namespace_version(namespace)
    data = get_json(
        f"/users/{username}/wants",
        params={
            "page": page,
            "per_page": per_page,
        },
    )

    cache.set(
        namespace,
        cache_key,
        data,
        ttl_seconds=21600,
        expected_version=version,
    )

    return data

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
    per_page: int = DEFAULT_PER_PAGE,
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

def add_to_wantlist(release_id: int) -> dict:
    """Save to the signed-in owner's wantlist and invalidate their cached pages."""
    owner = current_credentials().username
    result = put_json(
        f"/users/{quote(owner, safe='')}/wants/{release_id}",
        payload={"release_id": release_id},
    )
    cache.clear_namespace(personal_namespace("wantlist_raw"))
    return result
