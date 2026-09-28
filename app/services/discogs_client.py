import os
import httpx
from dotenv import load_dotenv
from app.services.release_mapper import (
    discogs_to_release,
    collection_to_releases,
    inventory_to_listings
)
from app.models.release import Release

# Load environment variables from the local .env file.
load_dotenv()

BASE_URL = "https://api.discogs.com"

def get_release_raw(release_id: int) -> dict:
    """
    Retrieve a release directly from the Discogs API.
    For now this function returns the raw JSON response.
    Conversion to our internal Release model will be handled separately.
    """

    token = os.getenv("DISCOGS_TOKEN")

    if not token:
        raise RuntimeError("DISCOGS_TOKEN is missing from .env")

    headers = {
        "Authorization": f"Discogs token={token}",
        "User-Agent": "B-Side/0.1",
    }

    response = httpx.get(
        f"{BASE_URL}/releases/{release_id}",
        headers=headers,
        timeout=10.0,
    )

    response.raise_for_status()

    return response.json()

def get_release(release_id: int) -> Release:
    """
    Retrieve a Discogs release and convert it into internal model.
    """

    data = get_release_raw(release_id)

    return discogs_to_release(data)

def get_collection_raw(
    username: str,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """
    Retrieve the first page of a user's Discogs collection.
    Folder 0 represents the user's entire collection.
    For now, this function returns the raw Discogs response.
    Pagination will be handled separately.
    """

    token = os.getenv("DISCOGS_TOKEN")

    if not token:
        raise RuntimeError("DISCOGS_TOKEN is missing from .env")

    headers = {
        "Authorization": f"Discogs token={token}",
        "User-Agent": "B-Side/0.1",
    }

    response = httpx.get(
        f"{BASE_URL}/users/{username}/collection/folders/0/releases",
        headers=headers,
        params={
            "page": page,
            "per_page": per_page,
        },
        timeout=10.0,
    )

    response.raise_for_status()

    return response.json()

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
    """
    Retrieve one page of a Discogs seller's inventory.

    For now the raw API response is returned so that we can inspect
    the Marketplace data structure before mapping it to our models.
    """

    token = os.getenv("DISCOGS_TOKEN")

    if not token:
        raise RuntimeError("DISCOGS_TOKEN is missing from .env")

    headers = {
        "Authorization": f"Discogs token={token}",
        "User-Agent": "B-Side/0.1",
    }

    response = httpx.get(
        f"{BASE_URL}/users/{username}/inventory",
        headers=headers,
        params={
            "page": page,
            "per_page": per_page,
        },
        timeout=10.0,
    )

    response.raise_for_status()

    return response.json()

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