import unittest

from app.services.release_mapper import discogs_to_release


class ReleaseCoverTests(unittest.TestCase):
    def test_youtube_links_retain_titles_and_embedding_flags(self):
        videos = [
            {"uri": "https://www.youtube.com/watch?v=abcdefghijk", "title": "Track A", "embed": True},
            {"uri": "https://youtu.be/lmnopqrstuv", "title": "Track B", "embed": False},
        ]
        release = discogs_to_release({"id": 1, "title": "Record", "videos": videos})
        self.assertEqual(release.videos, videos)

    def test_youtube_links_ignore_invalid_entries_and_duplicates(self):
        uri = "https://www.youtube.com/watch?v=abcdefghijk"
        release = discogs_to_release({"id": 1, "title": "Record", "videos": [
            {"uri": uri, "title": "Track", "embed": True}, {"uri": uri},
            {"uri": "javascript:alert(1)"}, {"uri": "https://youtube.com.example.org/video"},
            {"uri": "https://example.org/video"}, {"uri": "https://["},
            {"uri": None}, "invalid", {},
        ]})
        self.assertEqual(release.videos, [{"uri": uri, "title": "Track", "embed": True}])

    def test_missing_video_lists_are_empty(self):
        for videos in (None, []):
            self.assertEqual(discogs_to_release({"id": 1, "title": "Record", "videos": videos}).videos, [])
        self.assertEqual(discogs_to_release({"id": 1, "title": "Record"}).videos, [])

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
