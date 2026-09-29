from app.models.listing import Listing
from app.models.user_taste import TasteProfile
from app.models.inventory_item import InventoryItem
from app.models.release import Release


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

    year_score = score_year(
        summary.year,
        taste.years,
    )

    # Wantlist is an explicit user preference,
    # so it receives a strong ranking boost.
    if summary.in_wantlist:
        score += 0.50


    return (
        artist_score * 0.50
        + label_score * 0.40
        + year_score * 0.10
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
        if (
            listing.release_summary is not None
            and not listing.release_summary.in_collection
        )
    ]

    return sorted(
        scored,
        key=lambda item: item[1],
        reverse=True,
    )

def select_candidates(
    ranked_listings: list[tuple[Listing, float]],
    limit: int = 30,
) -> list[Listing]:
    """
    Select the highest ranked listings.
    """

    return [
        listing
        for listing, _ in ranked_listings[:limit]
    ]

def score_values(
    values: list[str],
    preferences: dict[str, int],
) -> float:
    """
    Score multiple metadata values against the user's taste.
    """

    if not values or not preferences:
        return 0.0

    max_count = max(preferences.values())

    scores = [
        preferences.get(value, 0) / max_count
        for value in values
    ]

    return sum(scores) / len(scores)


def score_release(
    release: Release,
    taste: TasteProfile,
) -> float:
    """
    Calculate the full recommendation score for a release.
    Unlike the pre-score, this uses the complete Discogs metadata.
    """

    style_score = score_values(release.styles, taste.styles)
    genre_score = score_values(release.genres, taste.genres)
    artist_score = score_values(release.artists, taste.artists)
    label_score = score_values(release.labels, taste.labels)

    year_score = score_preference(
        release.year,
        taste.years,
    )

    return (
        style_score * 0.40
        + genre_score * 0.40
        + artist_score * 0.05
        + label_score * 0.10
        + year_score * 0.05
    )


def rank_inventory_items(
    items: list[InventoryItem],
    taste: TasteProfile,
) -> list[tuple[InventoryItem, float]]:
    """Rank seller items using the full recommendation score."""

    scored = [
        (item, score_release(item.release, taste))
        for item in items
    ]

    return sorted(
        scored,
        key=lambda item: item[1],
        reverse=True,
    )

def score_year(
    year: int | None,
    preferences: dict[int, int],
) -> float:
    """
    Score a release year using a +/- 3 year window.
    """

    if year is None or not preferences:
        return 0.0

    weights = {
        0: 1.00,
        1: 0.75,
        2: 0.50,
        3: 0.25,
    }

    weighted_count = 0.0

    for preferred_year, count in preferences.items():
        distance = abs(year - preferred_year)

        if distance <= 3:
            weighted_count += count * weights[distance]

    max_count = max(preferences.values())

    return min(weighted_count / max_count, 1.0)