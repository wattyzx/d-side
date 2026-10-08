from app.models.release import Release
from app.models.listing import Listing
from app.models.release_summary import ReleaseSummary
from urllib.parse import urlsplit


def _youtube_videos(data: dict) -> list[dict]:
    videos = []
    seen = set()
    for video in data.get("videos") or []:
        if not isinstance(video, dict) or not isinstance(video.get("uri"), str):
            continue
        uri = video["uri"].strip()
        try:
            parsed = urlsplit(uri)
        except ValueError:
            continue
        if parsed.scheme not in ("http", "https") or parsed.hostname not in {
            "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
            "youtu.be", "www.youtu.be",
        } or uri in seen:
            continue
        seen.add(uri)
        videos.append({
            "uri": uri,
            "title": video.get("title") if isinstance(video.get("title"), str) else "",
            "embed": video.get("embed") is True,
        })
    return videos

def _cover_thumbnail(data: dict) -> str | None:
    images = data.get("images") or []
    primary = [image for image in images if image.get("type") == "primary"]
    candidates = [data.get("thumb"), data.get("cover_image")]
    for image in primary + [image for image in images if image.get("type") != "primary"]:
        candidates.extend((image.get("uri150"), image.get("uri")))
    return next((url for url in candidates
                 if isinstance(url, str) and url.startswith(("https://", "http://"))), None)

def discogs_to_release(data: dict) -> Release:

    artists = [
        artist["name"]
        for artist in data.get("artists", [])
        if artist.get("name")
    ]

    labels = [
        label["name"]
        for label in data.get("labels", [])
        if label.get("name")
    ]

    catalog_numbers = [
        label["catno"]
        for label in data.get("labels", [])
        if label.get("catno")
    ]

    formats = [
        release_format["name"]
        for release_format in data.get("formats", [])
        if release_format.get("name")
    ]

    return Release(
        id=data["id"],
        title=data["title"],
        artists=artists,
        year=data.get("year"),
        genres=data.get("genres", []),
        styles=data.get("styles", []),
        labels=labels,
        catalog_numbers=catalog_numbers,
        formats=formats,
        thumbnail_url=_cover_thumbnail(data),
        videos=_youtube_videos(data),
    )

def collection_item_to_release(item: dict) -> Release:
    """
    Convert a Discogs collection item into internal Release model.
    Collection responses store release metadata inside the
    'basic_information' field.
    """

    basic_information = item["basic_information"]

    return discogs_to_release(basic_information)

def collection_to_releases(collection_data: dict) -> list[Release]:
    """
    Convert all collection items in a Discogs collection response
    into release objects.
    """

    return [
        collection_item_to_release(item)
        for item in collection_data.get("releases", [])
    ]

def discogs_to_listing(data: dict) -> Listing:
    """
    Convert a raw Discogs Marketplace listing into listing model.
    """

    price = data["price"]
    release_data = data["release"]
    stats = release_data.get("stats", {}).get("community", {})

    summary = ReleaseSummary(
        artist=release_data.get("artist"),
        title=release_data.get("title"),
        year=release_data.get("year"),
        label=release_data.get("label"),
        catalog_number=release_data.get("catalog_number"),
        format=release_data.get("format"),
        community_have=stats.get("in_collection", 0),
        community_want=stats.get("in_wantlist", 0),
        thumbnail_url=_cover_thumbnail(release_data),

    )

    return Listing(
        id=data["id"],
        release_id=data["release"]["id"],
        price=price["value"],
        currency=price["currency"],
        condition=data["condition"],
        sleeve_condition=data.get("sleeve_condition"),
        release_summary=summary,
    )

def inventory_to_listings(inventory_data: dict) -> list[Listing]:
    """
    Convert all Marketplace listings in one Discogs inventory response
    into Listing objects.
    """

    return [
        discogs_to_listing(item)
        for item in inventory_data.get("listings", [])
    ]
