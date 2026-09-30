from functools import lru_cache
from math import log1p
from app.models.listing import Listing
from app.models.user_taste import TasteProfile
from app.models.inventory_item import InventoryItem
from app.models.release import Release

DEMAND_SMOOTHING = 20
DEMAND_BONUS_WEIGHT = 0.30

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

    return (
        artist_score * 0.50
        + label_score * 0.40
        + year_score * 0.10
    )

def rank_listings(
    listings: list[Listing],
    taste: TasteProfile,
    collection_ids: set[int],
) -> list[tuple[Listing, float]]:

    candidates = [
        listing
        for listing in listings
        if listing.release_id
        not in collection_ids
    ]

    raw_taste_scores = {
        listing.release_id:
            pre_score_listing(
                listing,
                taste,
            )
        for listing in candidates
    }

    raw_demand_scores = {
        listing.release_id:
            score_demand(
                listing
            )
        for listing in candidates
    }

    taste_scores = normalize_scores(
        raw_taste_scores
    )

    demand_scores = normalize_scores(
        raw_demand_scores
    )

    ranked = [
        (
            listing,
            score_candidate(
                taste_scores.get(
                    listing.release_id,
                    0.0,
                ),
                demand_scores.get(
                    listing.release_id,
                    0.0,
                ),
            ),
        )
        for listing in candidates
    ]

    return sorted(
        ranked,
        key=lambda item: item[1],
        reverse=True,
    )

def select_candidates(
    ranked_listings: list[tuple[Listing, float]],
    wantlist_ids: set[int],
    collection_ids: set[int],
    limit: int = 30,
) -> list[Listing]:
    """
    Select one representative listing per candidate release.
    Wantlisted and already owned releases are excluded from this pool.
    Other copies remain available in the original inventory.
    """

    if limit <= 0:
        return []

    candidates = []
    seen = wantlist_ids | collection_ids
    for listing, _ in ranked_listings:
        if listing.release_id in seen:
            continue
        seen.add(listing.release_id)
        candidates.append(listing)
        if len(candidates) == limit:
            break

    return candidates


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

@lru_cache(maxsize=128)
def _year_scores(preferences: tuple[tuple[int, int], ...]) -> dict[int, float]:
    """Compute the normalized year lookup once per profile snapshot."""
    scores: dict[int, float] = {}
    for preferred_year, count in preferences:
        for offset in range(-3, 4):
            year = preferred_year + offset
            scores[year] = scores.get(year, 0.0) + count * (1 - abs(offset) / 4)

    maximum = max(scores.values(), default=0.0)
    if maximum == 0:
        return {}
    return {year: score / maximum for year, score in scores.items()}


def score_year(
    year: int | None,
    preferences: dict[int, int],
) -> float:
    if year is None or not preferences:
        return 0.0

    # A content-based key also invalidates the cache when a profile is edited.
    return _year_scores(tuple(sorted(preferences.items()))).get(year, 0.0)

def score_release_breakdown(
    release: Release,
    taste: TasteProfile,
) -> dict[str, float]:

    style_score = score_styles(
        release.styles,
        taste.styles,
    )

    genre_score = score_values(
        release.genres,
        taste.genres,
    )

    artist_score = score_values(
        release.artists,
        taste.artists,
    )

    label_score = score_values(
        release.labels,
        taste.labels,
    )

    year_score = score_year(
        release.year,
        taste.years,
    )

    # Styles describe the core musical compatibility.
    # Artist, label and year act as positive confidence signals.
    #
    # Unknown artist / label no longer reduce the maximum
    # score a stylistically strong release can achieve.

    bonus = (
        artist_score * 0.40
        + label_score * 0.40
        + year_score * 0.20
    )

    total = (
        style_score
        + (1 - style_score) * bonus
    )

    return {
        "styles": style_score,
        "genres": genre_score,
        "artists": artist_score,
        "labels": label_score,
        "year": year_score,
        "bonus": bonus,
        "total": total,
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

def get_wantlist_matches(
    listings: list[Listing],
    wantlist_ids: set[int],
    collection_ids: set[int],
) -> list[Listing]:
    """
    Return seller listings explicitly present in the user's wantlist.
    Already owned releases are excluded.
    """

    return [
        listing
        for listing in listings
        if (
            listing.release_id in wantlist_ids
            and listing.release_id not in collection_ids
        )
    ]


### PRE LISTING METHOD USING WANT/HAVE RATIO TO ESTABLISH DEMAN AND START FROM THERE

def score_demand(listing: Listing) -> float:
    summary = listing.release_summary

    if summary is None:
        return 0.0

    want = max(
        0,
        summary.community_want,
    )

    have = max(
        0,
        summary.community_have,
    )

    if want == 0:
        return 0.0

    relative_demand = (
        want
        / (
            want
            + have
            + DEMAND_SMOOTHING
        )
    )

    confidence = log1p(
        want + have
    )

    return (
        relative_demand
        * confidence
    )


def normalize_scores(
    scores: dict[int, float],
) -> dict[int, float]:

    if not scores:
        return {}

    max_score = max(
        scores.values()
    )

    if max_score <= 0:
        return {
            key: 0.0
            for key in scores
        }

    return {
        key: value / max_score
        for key, value
        in scores.items()
    }


def score_candidate(
    taste_score: float,
    demand_score: float,
) -> float:

    return (
        taste_score
        + DEMAND_BONUS_WEIGHT
        * demand_score
        * (1 - taste_score)
    )