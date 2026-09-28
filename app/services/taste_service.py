from collections import Counter

from app.models.release import Release
from app.models.user_taste import TasteProfile


def count_styles(releases: list[Release]) -> dict[str, int]:
    counts = Counter()

    for release in releases:
        counts.update(release.styles)

    return dict(counts)


def count_genres(releases: list[Release]) -> dict[str, int]:
    counts = Counter()

    for release in releases:
        counts.update(release.genres)

    return dict(counts)


def count_artists(releases: list[Release]) -> dict[str, int]:
    counts = Counter()

    for release in releases:
        counts.update(release.artists)

    return dict(counts)


def count_labels(releases: list[Release]) -> dict[str, int]:
    counts = Counter()

    for release in releases:
        counts.update(release.labels)

    return dict(counts)


def count_years(releases: list[Release]) -> dict[int, int]:
    counts = Counter(
        release.year
        for release in releases
        if release.year is not None
    )

    return dict(counts)


def build_taste_profile(releases: list[Release]) -> TasteProfile:
    """Build a taste profile from a collection."""

    return TasteProfile(
        artists=count_artists(releases),
        genres=count_genres(releases),
        styles=count_styles(releases),
        labels=count_labels(releases),
        years=count_years(releases),
    )