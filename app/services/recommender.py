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
    return score_release_breakdown(release, taste)["total"]


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
    if year is None or not preferences:
        return 0.0

    weights = {
        0: 1.00,
        1: 0.75,
        2: 0.50,
        3: 0.25,
    }

    def local_score(target_year: int) -> float:
        score = 0.0

        for preferred_year, count in preferences.items():
            distance = abs(target_year - preferred_year)

            if distance <= 3:
                score += count * weights[distance]

        return score

    year_score = local_score(year)

    min_year = min(preferences)
    max_year = max(preferences)

    max_possible_score = max(
        local_score(candidate_year)
        for candidate_year in range(min_year - 3, max_year + 4)
    )

    if max_possible_score == 0:
        return 0.0

    return year_score / max_possible_score

def score_release_breakdown(
    release: Release,
    taste: TasteProfile,
) -> dict[str, float]:
    """
    Return the individual components of the full recommendation score.
    """

    style_score = score_styles(release.styles, taste.styles)
    genre_score = score_values(release.genres, taste.genres)
    artist_score = score_values(release.artists, taste.artists)
    label_score = score_values(release.labels, taste.labels)
    year_score = score_year(release.year, taste.years)

    total_score = (
        style_score * 0.60
        + genre_score * 0.05
        + artist_score * 0.15
        + label_score * 0.20
        + year_score * 0.05
    )

    return {
        "styles": style_score,
        "genres": genre_score,
        "artists": artist_score,
        "labels": label_score,
        "year": year_score,
        "total": total_score,
    }

def score_styles(
    styles: list[str],
    preferences: dict[str, int],
) -> float:
    """
    Score release styles against the user's taste.

    Multiple matching styles increase the score instead of being averaged.
    """

    if not styles or not preferences:
        return 0.0

    max_count = max(preferences.values())

    scores = [
        (preferences.get(style, 0) / max_count) * 0.60        #stile/frequenza per un peso (meno valore signolo stile)
        for style in styles
    ]

    combined_score = 0.0

    for score in scores:
        combined_score = 1 - (1 - combined_score) * (1 - score)

    return combined_score