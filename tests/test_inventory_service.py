import unittest
from unittest.mock import patch

import httpx

from app.models.listing import Listing
from app.models.release import Release
from app.services import inventory_service
from app.services.release_cache import ReleaseCache

from app.services.inventory_service import choose_inventory_pages


class InventorySamplingTests(unittest.TestCase):

    def test_stratified_sampling(self):
        self.assertEqual(
            choose_inventory_pages(44, 10),
            [1, 6, 11, 15, 20, 25, 30, 34, 39, 44],
        )

    def test_sample_larger_than_inventory_returns_all_pages(self):
        self.assertEqual(
            choose_inventory_pages(5, 10),
            [1, 2, 3, 4, 5],
        )

    def test_single_page_sample(self):
        self.assertEqual(
            choose_inventory_pages(44, 1),
            [1],
        )

    def test_invalid_values(self):
        self.assertEqual(choose_inventory_pages(0, 10), [])
        self.assertEqual(choose_inventory_pages(10, 0), [])


class InventoryEnrichmentTests(unittest.TestCase):
    def test_unavailable_copies_are_skipped_once_per_batch_and_can_be_retried_later(self):
        missing = Listing(1, 10, 5, "EUR", "Mint (M)")
        duplicate = Listing(2, 10, 6, "EUR", "Mint (M)")
        available = Listing(3, 20, 7, "EUR", "Mint (M)")
        for status in (404, 410):
            with self.subTest(status=status):
                def fetch(release_id, **kwargs):
                    if release_id == 10:
                        response = httpx.Response(status, request=httpx.Request(
                            "GET", "https://api.discogs.com/releases/10"
                        ))
                        response.raise_for_status()
                    return Release(20, "Available")

                with patch.object(inventory_service, "_release_cache", ReleaseCache(100, 60)), \
                     patch.object(inventory_service, "get_release", side_effect=fetch) as lookup:
                    items = inventory_service.link_inventory([missing, duplicate, available])
                    self.assertEqual([item.release.id for item in items], [20])
                    self.assertEqual([call.args[0] for call in lookup.call_args_list], [10, 20])
                    inventory_service.link_inventory([missing, duplicate])
                    self.assertEqual([call.args[0] for call in lookup.call_args_list], [10, 20, 10])
