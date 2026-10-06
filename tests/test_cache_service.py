import tempfile
import unittest

from pathlib import Path

from app.services.cache_service import (
    SQLiteCache,
    make_cache_key,
)


class FakeClock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class CacheServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.temp_dir.name)
            / "cache.sqlite3"
        )

        self.clock = FakeClock()

        self.cache = SQLiteCache(
            db_path=self.db_path,
            clock=self.clock,
        )


    def tearDown(self):
        self.temp_dir.cleanup()


    def test_set_and_get(self):
        value = {
            "id": 123,
            "title": "Test Release",
        }

        self.cache.set(
            "release",
            "123",
            value,
        )

        result = self.cache.get(
            "release",
            "123",
        )

        self.assertEqual(
            result,
            value,
        )


    def test_cache_persists_between_instances(self):
        self.cache.set(
            "release",
            "123",
            {
                "title": "Persistent Release",
            },
        )

        second_cache = SQLiteCache(
            db_path=self.db_path,
            clock=self.clock,
        )

        result = second_cache.get(
            "release",
            "123",
        )

        self.assertEqual(
            result,
            {
                "title": "Persistent Release",
            },
        )


    def test_missing_key_returns_none(self):
        result = self.cache.get(
            "release",
            "999",
        )

        self.assertIsNone(
            result
        )


    def test_namespaces_are_independent(self):
        self.cache.set(
            "release",
            "123",
            {
                "type": "release",
            },
        )

        self.cache.set(
            "inventory",
            "123",
            {
                "type": "inventory",
            },
        )

        release = self.cache.get(
            "release",
            "123",
        )

        inventory = self.cache.get(
            "inventory",
            "123",
        )

        self.assertEqual(
            release["type"],
            "release",
        )

        self.assertEqual(
            inventory["type"],
            "inventory",
        )


    def test_existing_value_is_overwritten(self):
        self.cache.set(
            "release",
            "123",
            {
                "version": 1,
            },
        )

        self.cache.set(
            "release",
            "123",
            {
                "version": 2,
            },
        )

        result = self.cache.get(
            "release",
            "123",
        )

        self.assertEqual(
            result["version"],
            2,
        )


    def test_value_expires(self):
        self.cache.set(
            "release",
            "123",
            {
                "title": "Temporary",
            },
            ttl_seconds=60,
        )

        self.clock.advance(
            59
        )

        self.assertIsNotNone(
            self.cache.get(
                "release",
                "123",
            )
        )

        self.clock.advance(
            2
        )

        self.assertIsNone(
            self.cache.get(
                "release",
                "123",
            )
        )


    def test_delete(self):
        self.cache.set(
            "release",
            "123",
            {
                "title": "Delete Me",
            },
        )

        self.cache.delete(
            "release",
            "123",
        )

        self.assertIsNone(
            self.cache.get(
                "release",
                "123",
            )
        )


    def test_clear_namespace(self):
        self.cache.set(
            "release",
            "1",
            {
                "id": 1,
            },
        )

        self.cache.set(
            "release",
            "2",
            {
                "id": 2,
            },
        )

        self.cache.set(
            "inventory",
            "1",
            {
                "id": 1,
            },
        )

        self.cache.clear_namespace(
            "release"
        )

        self.assertIsNone(
            self.cache.get(
                "release",
                "1",
            )
        )

        self.assertIsNone(
            self.cache.get(
                "release",
                "2",
            )
        )

        self.assertIsNotNone(
            self.cache.get(
                "inventory",
                "1",
            )
        )


    def test_clear_expired(self):
        self.cache.set(
            "release",
            "old",
            {
                "id": 1,
            },
            ttl_seconds=10,
        )

        self.cache.set(
            "release",
            "new",
            {
                "id": 2,
            },
            ttl_seconds=100,
        )

        self.clock.advance(
            20
        )

        self.cache.clear_expired()

        self.assertIsNone(
            self.cache.get(
                "release",
                "old",
            )
        )

        self.assertIsNotNone(
            self.cache.get(
                "release",
                "new",
            )
        )

    def test_cache_key_is_stable(self):
        key_a = make_cache_key(
            "https://api.discogs.com/releases/123",
            {
                "page": 1,
                "per_page": 100,
            },
        )

        key_b = make_cache_key(
            "https://api.discogs.com/releases/123",
            {
                "per_page": 100,
                "page": 1,
            },
        )

        self.assertEqual(
            key_a,
            key_b,
        )


    def test_different_params_create_different_keys(self):
        key_a = make_cache_key(
            "https://api.discogs.com/users/test/collection",
            {
                "page": 1,
            },
        )

        key_b = make_cache_key(
            "https://api.discogs.com/users/test/collection",
            {
                "page": 2,
            },
        )

        self.assertNotEqual(
            key_a,
            key_b,
        )


    def test_invalid_ttl_raises_error(self):
        with self.assertRaises(
            ValueError
        ):
            self.cache.set(
                "release",
                "123",
                {},
                ttl_seconds=0,
            )

    def test_invalidation_rejects_old_fetches_across_instances_without_overwriting_fresh_data(self):
        namespace = "wantlist_raw:alice"
        old_version = self.cache.namespace_version(namespace)
        other = SQLiteCache(self.db_path, clock=self.clock)
        # Invalidation must advance the version even when there are no rows.
        other.clear_namespace(namespace)
        self.assertFalse(self.cache.set(namespace, "page1", {"old": True}, expected_version=old_version))
        self.assertIsNone(other.get(namespace, "page1"))
        version = other.namespace_version(namespace)
        self.assertTrue(other.set(namespace, "page1", {"fresh": True}, expected_version=version))
        self.assertFalse(self.cache.set(namespace, "page1", {"old": True}, expected_version=old_version))
        self.assertEqual(self.cache.get(namespace, "page1"), {"fresh": True})
        other.clear_namespace(namespace)
        self.assertFalse(self.cache.set(namespace, "page2", {}, expected_version=version))

    def test_invalidation_versions_survive_cleanup_and_are_isolated_by_namespace(self):
        alice, bob = "wantlist_raw:alice", "wantlist_raw:bob"
        before = self.cache.namespace_version(alice)
        bob_version = self.cache.namespace_version(bob)
        self.cache.clear_namespace(alice)
        self.clock.advance(21600)
        self.cache.clear_expired()
        reopened = SQLiteCache(self.db_path, clock=self.clock)
        self.assertFalse(reopened.set(alice, "page1", {}, expected_version=before))
        self.assertTrue(reopened.set(bob, "page1", {}, expected_version=bob_version))


if __name__ == "__main__":
    unittest.main()
