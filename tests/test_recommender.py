import unittest
from unittest.mock import patch

from app.models.listing import Listing
from app.models.release import Release
from app.models.release_summary import ReleaseSummary
from app.models.user_taste import TasteProfile
from app.services import inventory_service
from app.services.recommender import (
    _year_scores, rank_listings, score_release, score_release_breakdown,
    score_year, select_candidates,
)
from app.services.taste_service import count_artists


def listing(listing_id, release_id, summary=None):
    return Listing(listing_id, release_id, 10, "EUR", "Mint (M)", release_summary=summary)


class RecommendationTests(unittest.TestCase):
    def test_style_match_is_the_musical_match_when_styles_are_available(self):
        taste = TasteProfile(styles={"House": 1}, genres={"Electronic": 1})
        release = Release(1, "House record", styles=["House"], genres=["Electronic"])
        scores = score_release_breakdown(release, taste)
        self.assertAlmostEqual(scores["musical_match"], 0.6)
        self.assertEqual(scores["musical_match"], scores["styles"])
        self.assertEqual(score_release(release, taste), scores["musical_match"])

    def test_genre_fallback_requires_missing_style_metadata(self):
        for release_styles, taste_styles, expected in (
            ([], {"House": 1}, 0.25),
            (["Techno"], {}, 0.25),
            (["Techno"], {"House": 1}, 0.0),
        ):
            with self.subTest(release_styles=release_styles, taste_styles=taste_styles):
                taste = TasteProfile(styles=taste_styles, genres={"Electronic": 1})
                release = Release(1, "Record", styles=release_styles, genres=["Electronic"])
                scores = score_release_breakdown(release, taste)
                self.assertEqual(scores["musical_match"], expected)
                self.assertEqual(scores["total"], expected)

    def test_supporting_metadata_cannot_create_a_perfect_musical_match(self):
        taste = TasteProfile(
            artists={"A": 1}, labels={"Label": 1}, years={2000: 1},
            styles={"House": 1}, genres={"Electronic": 1},
        )
        release = Release(
            1, "Unmatched style", artists=["A"], labels=["Label"], year=2000,
            styles=["Techno"], genres=["Electronic"],
        )
        scores = score_release_breakdown(release, taste)
        self.assertEqual(scores["musical_match"], 0)
        self.assertAlmostEqual(scores["bonus"], 0.35)
        self.assertAlmostEqual(scores["total"], 0.35)
        release.styles = ["House"]
        self.assertAlmostEqual(score_release(release, taste), 0.74)

    def test_missing_music_metadata_has_no_musical_match(self):
        scores = score_release_breakdown(Release(1, "Empty"), TasteProfile())
        self.assertEqual(scores["musical_match"], 0)
        self.assertEqual(scores["total"], 0)

    def test_duplicate_copies_do_not_use_candidate_slots(self):
        copies = [listing(i, 1) for i in range(30)]
        other = listing(30, 2)
        inventory = copies + [other]
        candidates = select_candidates([(item, 1.0) for item in inventory], set(), set(), 2)
        self.assertEqual(candidates, [copies[0], other])
        self.assertEqual(len(inventory), 31)

    def test_candidate_exclusions_and_limits(self):
        ranked = [(listing(i, i), 1.0) for i in range(5)]
        owned, wanted = {0}, {1}
        self.assertEqual(
            [item.release_id for item in select_candidates(ranked, wanted, owned, 2)],
            [2, 3],
        )
        self.assertEqual(owned, {0})
        self.assertEqual(wanted, {1})
        for limit in (0, -1):
            self.assertEqual(select_candidates(ranked, wanted, owned, limit), [])
        self.assertEqual(select_candidates([], wanted, owned), [])

    def test_ownership_uses_ids_even_when_summary_flag_disagrees(self):
        owned = listing(1, 10, ReleaseSummary(in_collection=False))
        unowned = listing(2, 20, ReleaseSummary(in_collection=True))
        no_summary = listing(3, 30)
        ranked = rank_listings([owned, unowned, no_summary], TasteProfile(), {10})
        self.assertEqual([item for item, _ in ranked], [unowned, no_summary])

    def test_weak_taste_match_is_not_rescaled_by_other_candidates(self):
        taste = TasteProfile(artists={"Occasional": 1, "Favorite": 5})
        weak = listing(1, 10, ReleaseSummary(artist="Occasional"))
        strong = listing(2, 20, ReleaseSummary(artist="Favorite"))
        self.assertAlmostEqual(rank_listings([weak], taste, set())[0][1], 0.1)
        scores = {
            item.release_id: score
            for item, score in rank_listings([weak, strong], taste, set())
        }
        self.assertAlmostEqual(scores[10], 0.1)
        self.assertAlmostEqual(scores[20], 0.5)

    def test_demand_bonus_uses_absolute_taste_score(self):
        taste = TasteProfile(years={2000: 1})
        item = listing(1, 10, ReleaseSummary(year=2000, community_want=100))
        # A year-only match scores 0.2, with up to 0.3 of the remaining 0.8
        # supplied by demand. It must not become a perfect taste match.
        self.assertAlmostEqual(rank_listings([item], taste, set())[0][1], 0.44)

    def test_year_scores_preserve_original_formula(self):
        preferences = {1980: 2, 1982: 4, 2000: 1}

        def original_local(year):
            return sum(
                count * (1 - abs(year - preferred) / 4)
                for preferred, count in preferences.items()
                if abs(year - preferred) <= 3
            )

        maximum = max(original_local(year) for year in range(1977, 2004))
        for year in range(1970, 2010):
            self.assertAlmostEqual(score_year(year, preferences), original_local(year) / maximum)
        self.assertEqual(score_year(None, preferences), 0)
        self.assertEqual(score_year(1980, {}), 0)

    def test_year_lookup_is_reused_and_profile_edits_invalidate_it(self):
        _year_scores.cache_clear()
        preferences = {1980: 1, 2000: 2}
        self.assertEqual(score_year(1980, preferences), 0.5)
        self.assertEqual(score_year(2000, preferences), 1)
        self.assertEqual(_year_scores.cache_info().misses, 1)
        preferences[1980] = 4
        self.assertEqual(score_year(1980, preferences), 1)
        self.assertEqual(_year_scores.cache_info().misses, 2)

    def test_artists_count_all_releases_and_ignore_placeholders(self):
        releases = [
            Release(1, "First", artists=["A", "B", "Various"]),
            Release(2, "Second", artists=["A", "Unknown Artist"]),
        ]
        self.assertEqual(count_artists(releases), {"A": 2, "B": 1})
        self.assertEqual(count_artists([]), {})

    def test_inventory_preserves_copies_and_fetches_each_release_once(self):
        copies = [listing(1, 10), listing(2, 10), listing(3, 20)]
        with patch.dict(inventory_service._release_cache, {}, clear=True):
            with patch.object(inventory_service, "get_release", side_effect=[Release(10, "A"), Release(20, "B")]) as fetch:
                items = inventory_service.link_inventory(copies, delay=2)
                self.assertEqual([item.listing for item in items], copies)
                self.assertIs(items[0].release, items[1].release)
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(fetch.call_args.kwargs, {"min_interval": 2})
                fetch.reset_mock()
                inventory_service.link_inventory(copies)
                fetch.assert_not_called()
                self.assertEqual(inventory_service.link_inventory([]), [])


if __name__ == "__main__":
    unittest.main()
