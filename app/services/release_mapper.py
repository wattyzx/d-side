from app.models.release import Release


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