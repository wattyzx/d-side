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