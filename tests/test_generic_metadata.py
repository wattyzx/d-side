import unittest

from app.models.listing import Listing
from app.models.release import Release
from app.models.release_summary import ReleaseSummary
from app.models.user_taste import TasteProfile
from app.services.recommender import pre_score_listing, score_release_breakdown
from app.services.taste_service import build_taste_profile


GENERIC_ARTISTS = [
    "Various", "Various Artist", "Various Artists", "Unknown",
    "Unknown Artist", "Unknown Artists", "  various   ARTISTS  ",
    "Unknown Artist (2)", "", "   ",
]
GENERIC_LABELS = [
    "Unknown", "Unknown Label", "Not On Label", "White Label",
    "  NOT   on LABEL  ", "Unknown Label (2)", "", "   ",
]


class GenericMetadataTests(unittest.TestCase):
    def test_profile_excludes_placeholders_but_preserves_specific_names(self):
        release = Release(
            1, "Mixed metadata",
            artists=GENERIC_ARTISTS + ["Unknown Mortal Orchestra", "A (2)"],
            labels=GENERIC_LABELS + ["Unknown To The Unknown", "Label (2)"],
            styles=["House"], genres=["Electronic"], year=2000,
        )
        taste = build_taste_profile([release, release])
        self.assertEqual(taste.artists, {"Unknown Mortal Orchestra": 2, "A (2)": 2})
        self.assertEqual(taste.labels, {"Unknown To The Unknown": 2, "Label (2)": 2})
        self.assertEqual(taste.styles, {"House": 2})
        self.assertEqual(taste.genres, {"Electronic": 2})
        self.assertEqual(taste.years, {2000: 2})

    def test_placeholder_only_metadata_has_no_score_even_in_existing_profile(self):
        taste = TasteProfile(
            artists=dict.fromkeys(GENERIC_ARTISTS, 100),
            labels=dict.fromkeys(GENERIC_LABELS, 100),
        )
        for artist in GENERIC_ARTISTS + [None]:
            for label in GENERIC_LABELS + [None]:
                with self.subTest(artist=artist, label=label):
                    summary = ReleaseSummary(artist=artist, label=label)
                    listing = Listing(1, 1, 10, "EUR", "Mint (M)", release_summary=summary)
                    self.assertEqual(pre_score_listing(listing, taste), 0)
        scores = score_release_breakdown(
            Release(1, "Generic", artists=GENERIC_ARTISTS, labels=GENERIC_LABELS),
            taste,
        )
        self.assertEqual(scores["artists"], 0)
        self.assertEqual(scores["labels"], 0)
        self.assertEqual(scores["total"], 0)

    def test_placeholders_do_not_dilute_valid_matches_or_change_other_signals(self):
        clean_taste = TasteProfile(
            artists={"A": 2, "B": 4}, labels={"Label": 3, "Other": 6},
            styles={"House": 1}, genres={"Electronic": 1}, years={2000: 1},
        )
        dirty_taste = TasteProfile(
            artists={**clean_taste.artists, **dict.fromkeys(GENERIC_ARTISTS, 100)},
            labels={**clean_taste.labels, **dict.fromkeys(GENERIC_LABELS, 100)},
            styles=clean_taste.styles, genres=clean_taste.genres, years=clean_taste.years,
        )
        listing = Listing(
            1, 1, 10, "EUR", "Mint (M)",
            release_summary=ReleaseSummary(artist="A", label="Label", year=2000),
        )
        self.assertAlmostEqual(pre_score_listing(listing, clean_taste), 0.6)
        self.assertEqual(
            pre_score_listing(listing, dirty_taste), pre_score_listing(listing, clean_taste),
        )
        release = Release(
            1, "Specific", artists=["A"], labels=["Label"],
            styles=["House"], genres=["Electronic"], year=2000,
        )
        expected = score_release_breakdown(release, clean_taste)
        release.artists += GENERIC_ARTISTS
        release.labels += GENERIC_LABELS
        self.assertEqual(score_release_breakdown(release, dirty_taste), expected)
        self.assertEqual(expected["artists"], 0.5)
        self.assertEqual(expected["labels"], 0.5)
        self.assertAlmostEqual(expected["total"], 0.68)


if __name__ == "__main__":
    unittest.main()
