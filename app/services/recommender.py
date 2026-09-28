from app.models.listing import Listing
from app.models.user_taste import TasteProfile


def score_preference(
    value: str | int | None,
    preferences: dict,
) -> float:
    """
    Score a single value against the user's collection preferences.
    The most frequent value scores 1.0.
    Missing or unknown values score 0.0.
    """

    if value is None or not preferences:
        return 0.0

    max_count = max(preferences.values())
    count = preferences.get(value, 0)

    return count / max_count

def pre_score_listing(
    listing: Listing,
    taste: TasteProfile,
) -> float:
    """
    first-pass score using only metadata already available
    in the seller inventory.

    No additional Discogs release request is required.
    """

    summary = listing.release_summary

    if summary is None:
        return 0.0

    artist_score = score_preference(
        summary.artist,
        taste.artists,
    )

    label_score = score_preference(
        summary.label,
        taste.labels,
    )

    year_score = score_preference(
        summary.year,
        taste.years,
    )

    return (
        artist_score * 0.40
        + label_score * 0.40
        + year_score * 0.20
    )


def rank_listings(
    listings: list[Listing],
    taste: TasteProfile,
) -> list[tuple[Listing, float]]:
    """
    Rank seller listings by their lightweight pre-score.
    """

    scored = [
        (listing, pre_score_listing(listing, taste))
        for listing in listings
    ]

    return sorted(
        scored,
        key=lambda item: item[1],
        reverse=True,
    )