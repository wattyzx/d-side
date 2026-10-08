import unittest

from app.services.release_mapper import discogs_to_release


class ReleaseCoverTests(unittest.TestCase):
    def test_primary_thumbnail_is_preferred_to_secondary_and_full_size(self):
        release = discogs_to_release({"id": 1, "title": "Record", "images": [
            {"type": "secondary", "uri150": "https://example.com/back.jpg"},
            {"type": "primary", "uri150": "https://example.com/front-small.jpg",
             "uri": "https://example.com/front-large.jpg"},
        ]})
        self.assertEqual(release.thumbnail_url, "https://example.com/front-small.jpg")

    def test_basic_information_thumbnail_and_missing_images(self):
        release = discogs_to_release({"id": 1, "title": "Record", "thumb": "https://example.com/thumb.jpg"})
        self.assertEqual(release.thumbnail_url, "https://example.com/thumb.jpg")
        self.assertIsNone(discogs_to_release({"id": 1, "title": "Record"}).thumbnail_url)

    def test_falls_back_when_thumbnail_is_empty(self):
        release = discogs_to_release({"id": 1, "title": "Record", "images": [
            {"type": "primary", "uri150": "", "uri": "https://example.com/front.jpg"},
        ]})
        self.assertEqual(release.thumbnail_url, "https://example.com/front.jpg")

    def test_unsupported_image_urls_are_ignored(self):
        release = discogs_to_release({"id": 1, "title": "Record", "thumb": "javascript:alert(1)"})
        self.assertIsNone(release.thumbnail_url)
