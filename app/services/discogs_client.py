import os
import httpx
from dotenv import load_dotenv

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