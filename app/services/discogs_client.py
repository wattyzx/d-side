import os
import httpx
from dotenv import load_dotenv
from app.services.release_mapper import discogs_to_release
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

def get_collection_raw(username: str) -> dict:
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
        timeout=10.0,
    )

    response.raise_for_status()

    return response.json()