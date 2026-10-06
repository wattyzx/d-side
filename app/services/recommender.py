from dataclasses import dataclass
from functools import lru_cache
from math import log1p
from app.models.listing import Listing
from app.models.user_taste import TasteProfile
from app.models.inventory_item import InventoryItem
from app.models.release import Release
from app.services.generic_metadata import is_generic_artist, is_generic_label
from app.services.search_control import check_cancelled

DEMAND_SMOOTHING = 20
DEMAND_BONUS_WEIGHT = 0.30
GENRE_FALLBACK_WEIGHT = 0.25


@dataclass(frozen=True)
class PreparedTaste:
    """Normalized preference snapshot, prepared once for a recommendation run."""

    artists: dict[str, float]
    labels: dict[str, float]
    styles: dict[str, float]
    genres: dict[str, float]
    years: dict[int, float]


def _normalized_preferences(preferences, is_generic=None):
    filtered = {}
    for value, count in preferences.items():
        check_cancelled()
        if is_generic is None or not is_generic(value):
            filtered[value] = count
    maximum = max(filtered.values(), default=0)
    if maximum == 0:
        return {}
    return {value: count / maximum for value, count in filtered.items()}


def prepare_taste(taste: TasteProfile | PreparedTaste) -> PreparedTaste:
    check_cancelled()
    if isinstance(taste, PreparedTaste):
        return taste
    return PreparedTaste(
        artists=_normalized_preferences(taste.artists, is_generic_artist),
        labels=_normalized_preferences(taste.labels, is_generic_label),
        styles=_normalized_preferences(taste.styles),
        genres=_normalized_preferences(taste.genres),
        years=_year_scores(tuple(sorted(taste.years.items()))),
    )


def _average_preference(values, preferences):
    if not values or not preferences:
        return 0.0
    return sum(preferences.get(value, 0.0) for value in values) / len(values)


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
    taste: TasteProfile | PreparedTaste,
) -> float:
    taste = prepare_taste(taste)
    summary = listing.release_summary

    if summary is None:
        return 0.0

    artist_score = taste.artists.get(summary.artist, 0.0)
    label_score = taste.labels.get(summary.label, 0.0)
    year_score = taste.years.get(summary.year, 0.0)

    return (
        artist_score * 0.50
        + label_score * 0.30
        + year_score * 0.20
    )

class ListingRanker:
    """Retain base scores across pages while updating inventory-wide demand."""

    def __init__(self, taste: TasteProfile | PreparedTaste, collection_ids: set[int]):
        self.taste = prepare_taste(taste)
        self.collection_ids = collection_ids
        self.listings: list[Listing] = []
        self.taste_scores: dict[int, float] = {}
        self.demand_scores: dict[int, float] = {}

    def add(self, listings: list[Listing]):
        for listing in listings:
            check_cancelled()
            if listing.release_id in self.collection_ids:
                continue
            self.listings.append(listing)
            # Preserve the existing last-copy metadata rule for a release;
            # stable sorting still chooses the first listing when scores tie.
            self.taste_scores[listing.release_id] = pre_score_listing(listing, self.taste)
            self.demand_scores[listing.release_id] = score_demand(listing)

    def ranked(self) -> list[tuple[Listing, float]]:
        check_cancelled()
        maximum = max(self.demand_scores.values(), default=0.0)
        ranked = []
        for listing in self.listings:
            check_cancelled()
            demand = self.demand_scores[listing.release_id] / maximum if maximum > 0 else 0.0
            ranked.append((listing, score_candidate(self.taste_scores[listing.release_id], demand)))
        ranked.sort(key=lambda item: (-item[1], item[0].release_id))
        check_cancelled()
        return ranked


def rank_listings(
    listings: list[Listing],
    taste: TasteProfile | PreparedTaste,
    collection_ids: set[int],
) -> list[tuple[Listing, float]]:
    ranker = ListingRanker(taste, collection_ids)
    ranker.add(listings)
    return ranker.ranked()

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
        check_cancelled()
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
    taste: TasteProfile | PreparedTaste,
) -> float:
    
    """
    Calculate the full recommendation score for a release.
    Unlike the pre-score, this uses the complete Discogs metadata.
    """
    return score_release_breakdown(release, taste)["total"]


def rank_inventory_items(
    items: list[InventoryItem],
    taste: TasteProfile | PreparedTaste,
) -> list[tuple[InventoryItem, float]]:
    """Rank seller items using the full recommendation score."""

    taste = prepare_taste(taste)
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
        check_cancelled()
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
    taste: TasteProfile | PreparedTaste,
) -> dict[str, float]:
    taste = prepare_taste(taste)
    style_score = 0.0
    for style in release.styles:
        check_cancelled()
        style_score = 1 - (1 - style_score) * (1 - taste.styles.get(style, 0.0) * 0.60)

    genre_score = _average_preference(release.genres, taste.genres)
    # Use genre as weak evidence only when a style comparison is unavailable.
    # Present but unmatched styles must not receive the genre fallback.
    musical_match = (
        style_score
        if release.styles and taste.styles
        else GENRE_FALLBACK_WEIGHT * genre_score
    )

    artist_score = _average_preference(
        [artist for artist in release.artists if not is_generic_artist(artist)],
        taste.artists,
    )

    label_score = _average_preference(
        [label for label in release.labels if not is_generic_label(label)],
        taste.labels,
    )

    year_score = taste.years.get(release.year, 0.0)

    # Supporting metadata can contribute at most 0.35 of the remaining score.
    bonus = (
        artist_score * 0.15
        + label_score * 0.15
        + year_score * 0.05
    )

    total = (
        musical_match
        + (1 - musical_match) * bonus
    )

    return {
        "styles": style_score,
        "genres": genre_score,
        "musical_match": musical_match,
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

def select_deterministic_exploration(
    listings: list[Listing],
    count: int,
) -> list[Listing]:

    if count <= 0:
        return []

    if len(listings) <= count:
        return listings.copy()

    step = len(listings) / count

    indices = [
        int((index + 0.5) * step)
        for index in range(count)
    ]

    return [
        listings[index]
        for index in indices
    ]

def select_progressive_batch(
    pre_ranked_listings: list[Listing],
    selected_ids: set[int],
    exploit_size: int = 25,
    explore_size: int = 5,
) -> tuple[list[Listing], list[Listing]]:
    """Take top ranks, then evenly sample the remaining unique releases."""

    unselected = [
        listing
        for listing in pre_ranked_listings
        if listing.release_id
        not in selected_ids
    ]

    exploit = unselected[
        :exploit_size
    ]

    remaining = unselected[
        exploit_size:
    ]

    explore = (
        select_deterministic_exploration(
            remaining,
            explore_size,
        )
    )

    return exploit, explore

def score_artists(
    artists: list[str],
    preferences: dict[str, int],
) -> float:
    """Ignore placeholders in both matches and preference normalization."""
    return score_values(
        [artist for artist in artists if not is_generic_artist(artist)],
        {
            artist: count for artist, count in preferences.items()
            if not is_generic_artist(artist)
        },
    )


def score_labels(
    labels: list[str],
    preferences: dict[str, int],
) -> float:
    """Ignore placeholders in both matches and preference normalization."""
    return score_values(
        [label for label in labels if not is_generic_label(label)],
        {
            label: count for label, count in preferences.items()
            if not is_generic_label(label)
        },
    )
